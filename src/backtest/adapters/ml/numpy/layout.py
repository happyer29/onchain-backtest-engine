"""Exact NumPy mmap schemas for immutable ML artifacts."""

from __future__ import annotations

from typing import Final

from backtest.adapters.ml.numpy.toolchain import (
    NUMPY_ML_COMPILER_VERSION,
    UNIT_ML_COMPILER_BUNDLE_ID,
    # Include unit ml writer bundle id so the toolchain dependency remains explicit.
    UNIT_ML_WRITER_BUNDLE_ID,
)
from backtest.application.ml_artifacts import MlArrayLayout, MlLayoutManifest
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import BundleId, ContentDigest

# Bind compiler version once as an explicit module-level contract.
COMPILER_VERSION: Final = NUMPY_ML_COMPILER_VERSION
COMPILER_BUNDLE_ID: Final = BundleId(UNIT_ML_COMPILER_BUNDLE_ID.hex)
WRITER_BUNDLE_ID: Final = BundleId(UNIT_ML_WRITER_BUNDLE_ID.hex)
WRITER_SETTINGS_DIGEST: Final[ContentDigest] = domain_digest(
    "backtest.numpy-ml-writer-settings.v1",
    # Open the v1 and allow pickle payload explicitly for domain_digest within module.
    {
        "allow_pickle": False,
        "array_order": "C",
        "numeric_byte_order": "little",
        "semantic_values": "signed-int64-v1",
        # Close the v1 and allow pickle payload only after all module fields are present.
    },
)

FEATURE_ROW_ID: Final = "features/replay_row_id.npy"
FEATURE_AVAILABLE: Final = "features/available_boundary_ordinal.npy"
FEATURE_VALUES: Final = "features/values.npy"
# Bind feature validity once as an explicit module-level contract.
FEATURE_VALIDITY: Final = "features/values.validity.npy"

UNIVERSE_ENTITY_ID: Final = "universe/entity_id.npy"
UNIVERSE_ELIGIBLE_FROM: Final = "universe/eligible_from.npy"
UNIVERSE_ELIGIBLE_UNTIL: Final = "universe/eligible_until.npy"
UNIVERSE_INPUT_AVAILABLE: Final = "universe/input_available_boundary.npy"

# Bind label row id once as an explicit module-level contract.
LABEL_ROW_ID: Final = "labels/replay_row_id.npy"
LABEL_EFFECTIVE: Final = "labels/effective_boundary_ordinal.npy"
LABEL_FUTURE_USED: Final = "labels/future_boundary_used.npy"
LABEL_VALUE: Final = "labels/value.npy"
LABEL_VALIDITY: Final = "labels/value.validity.npy"

# Bind model weights once as an explicit module-level contract.
MODEL_WEIGHTS: Final = "model/weights.npy"
MODEL_INTERCEPT: Final = "model/intercept.npy"

SCHEDULE_ELIGIBLE_FROM: Final = "schedule/eligible_from.npy"
SCHEDULE_ELIGIBLE_UNTIL: Final = "schedule/eligible_until.npy"
SCHEDULE_MODEL_ID: Final = "schedule/model_bundle_id.npy"
# Bind schedule training cutoff once as an explicit module-level contract.
SCHEDULE_TRAINING_CUTOFF: Final = "schedule/training_cutoff.npy"
SCHEDULE_MODEL_AVAILABLE: Final = "schedule/model_available_boundary.npy"
SCHEDULE_AVAILABILITY_BASIS: Final = "schedule/availability_basis_digest.npy"

PREDICTION_ROW_ID: Final = "predictions/replay_row_id.npy"
PREDICTION_EFFECTIVE: Final = "predictions/effective_boundary_ordinal.npy"
# Bind prediction available once as an explicit module-level contract.
PREDICTION_AVAILABLE: Final = "predictions/available_boundary_ordinal.npy"
PREDICTION_FEATURE_AVAILABLE: Final = "predictions/feature_available_boundary.npy"
PREDICTION_INFERENCE_COMPLETION: Final = "predictions/inference_completion_boundary.npy"
PREDICTION_MODEL_CODE: Final = "predictions/model_code.npy"
PREDICTION_VALUE: Final = "predictions/value.npy"
# Bind prediction validity once as an explicit module-level contract.
PREDICTION_VALIDITY: Final = "predictions/value.validity.npy"


def feature_layout(row_count: int, feature_count: int) -> MlLayoutManifest:
    # Execute the feature layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _u64(FEATURE_AVAILABLE, row_count, "feature.available_boundary_ordinal"),
            _u64(FEATURE_ROW_ID, row_count, "feature.replay_row_id"),
            MlArrayLayout(
                # Pass path explicitly so MlArrayLayout receives a reviewable <i8 and
                # values input in feature layout.
                path=FEATURE_VALUES,
                dtype="<i8",
                shape=(row_count, feature_count),
                role="feature.values",
                byte_order="little",
                # Pass overflow policy explicitly so MlArrayLayout receives a reviewable
                # <i8 and values input in feature layout.
                overflow_policy="checked-int64-v1",
            ),
            MlArrayLayout(
                path=FEATURE_VALIDITY,
                dtype="|u1",
                # Pass shape explicitly so MlArrayLayout receives a reviewable |u1 and
                # validity input in feature layout.
                shape=(feature_count, (row_count + 7) // 8),
                role="feature.validity",
                byte_order="not-applicable",
                overflow_policy="packed-lsb0-one-is-valid-v1",
            ),
            # Close the available boundary ordinal and replay row id payload only after all
            # feature layout fields are present.
        ]
    )


def universe_layout(row_count: int) -> MlLayoutManifest:
    # Execute the universe layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _u64(UNIVERSE_ELIGIBLE_FROM, row_count, "universe.eligible_from"),
            _u64(UNIVERSE_ELIGIBLE_UNTIL, row_count, "universe.eligible_until"),
            _u64(UNIVERSE_ENTITY_ID, row_count, "universe.entity_id"),
            # Include u64 in the completed universe layout result.
            _u64(
                UNIVERSE_INPUT_AVAILABLE,
                row_count,
                "universe.input_available_boundary",
            ),
            # Close the eligible from and eligible until payload only after all universe
            # layout fields are present.
        ]
    )


def label_layout(row_count: int) -> MlLayoutManifest:
    # Execute the label layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _u64(LABEL_EFFECTIVE, row_count, "label.effective_boundary_ordinal"),
            _u64(LABEL_FUTURE_USED, row_count, "label.future_boundary_used"),
            _u64(LABEL_ROW_ID, row_count, "label.replay_row_id"),
            # Include i64 in the completed label layout result.
            _i64(LABEL_VALUE, row_count, "label.value"),
            _bitmap(LABEL_VALIDITY, row_count, "label.validity"),
        ]
    )


def model_layout(weight_count: int) -> MlLayoutManifest:
    # Execute the model layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _i64(MODEL_INTERCEPT, 1, "model.intercept"),
            _i64(MODEL_WEIGHTS, weight_count, "model.weights"),
        ]
        # Complete _layout only after its intercept and weights inputs are visible in model
        # layout.
    )


def schedule_layout(entry_count: int) -> MlLayoutManifest:
    # Execute the schedule layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _digest(
                SCHEDULE_AVAILABILITY_BASIS,
                entry_count,
                # Pass availability basis digest explicitly so _digest receives a
                # reviewable availability basis digest and schedule availability basis
                # input in schedule layout.
                "schedule.availability_basis_digest",
            ),
            _u64(SCHEDULE_ELIGIBLE_FROM, entry_count, "schedule.eligible_from"),
            _u64(SCHEDULE_ELIGIBLE_UNTIL, entry_count, "schedule.eligible_until"),
            _digest(SCHEDULE_MODEL_ID, entry_count, "schedule.model_bundle_id"),
            # Include u64 in the completed schedule layout result.
            _u64(
                SCHEDULE_MODEL_AVAILABLE,
                entry_count,
                "schedule.model_available_boundary",
            ),
            # Include u64 in the completed schedule layout result.
            _u64(SCHEDULE_TRAINING_CUTOFF, entry_count, "schedule.training_cutoff"),
        ]
    )


def prediction_layout(row_count: int) -> MlLayoutManifest:
    # Execute the prediction layout workflow in explicit, reviewable steps.
    return _layout(
        [
            _u64(
                PREDICTION_AVAILABLE,
                row_count,
                # Pass available boundary ordinal explicitly so _u64 receives a reviewable
                # available boundary ordinal and prediction available input in prediction
                # layout.
                "prediction.available_boundary_ordinal",
            ),
            _u64(
                PREDICTION_EFFECTIVE,
                row_count,
                # Pass effective boundary ordinal explicitly so _u64 receives a reviewable
                # effective boundary ordinal and prediction effective input in prediction
                # layout.
                "prediction.effective_boundary_ordinal",
            ),
            _u64(
                PREDICTION_FEATURE_AVAILABLE,
                row_count,
                # Pass feature available boundary explicitly so _u64 receives a reviewable
                # feature available boundary and prediction feature available input in
                # prediction layout.
                "prediction.feature_available_boundary",
            ),
            _u64(
                PREDICTION_INFERENCE_COMPLETION,
                row_count,
                # Pass inference completion boundary explicitly so _u64 receives a
                # reviewable inference completion boundary and prediction inference
                # completion input in prediction layout.
                "prediction.inference_completion_boundary",
            ),
            MlArrayLayout(
                path=PREDICTION_MODEL_CODE,
                dtype="<u4",
                # Pass shape explicitly so MlArrayLayout receives a reviewable <u4 and
                # model code input in prediction layout.
                shape=(row_count,),
                role="prediction.model_code",
                byte_order="little",
                overflow_policy="checked-uint32-code-v1",
            ),
            # Include u64 in the completed prediction layout result.
            _u64(PREDICTION_ROW_ID, row_count, "prediction.replay_row_id"),
            _i64(PREDICTION_VALUE, row_count, "prediction.value"),
            _bitmap(PREDICTION_VALIDITY, row_count, "prediction.validity"),
        ]
    )


# Define layout as one focused operation with an explicit boundary.
def _layout(arrays: list[MlArrayLayout]) -> MlLayoutManifest:
    return MlLayoutManifest(tuple(sorted(arrays, key=lambda item: item.path)))


def _u64(path: str, count: int, role: str) -> MlArrayLayout:
    # Execute the u64 workflow in explicit, reviewable steps.
    return MlArrayLayout(
        path=path,
        dtype="<u8",
        shape=(count,),
        role=role,
        # Pass byte order explicitly so MlArrayLayout receives a reviewable <u8 and little
        # input in u64.
        byte_order="little",
        overflow_policy="checked-uint64-v1",
    )


def _i64(path: str, count: int, role: str) -> MlArrayLayout:
    # Execute the i64 workflow in explicit, reviewable steps.
    return MlArrayLayout(
        path=path,
        dtype="<i8",
        shape=(count,),
        role=role,
        # Pass byte order explicitly so MlArrayLayout receives a reviewable <i8 and little
        # input in i64.
        byte_order="little",
        overflow_policy="checked-int64-v1",
    )


def _bitmap(path: str, count: int, role: str) -> MlArrayLayout:
    # Execute the bitmap workflow in explicit, reviewable steps.
    return MlArrayLayout(
        path=path,
        dtype="|u1",
        shape=((count + 7) // 8,),
        role=role,
        # Pass byte order explicitly so MlArrayLayout receives a reviewable |u1 and not-
        # applicable input in bitmap.
        byte_order="not-applicable",
        overflow_policy="packed-lsb0-one-is-valid-v1",
    )


def _digest(path: str, count: int, role: str) -> MlArrayLayout:
    # Execute the digest workflow in explicit, reviewable steps.
    return MlArrayLayout(
        path=path,
        dtype="|V32",
        shape=(count,),
        role=role,
        # Pass byte order explicitly so MlArrayLayout receives a reviewable |v32 and not-
        # applicable input in digest.
        byte_order="not-applicable",
        overflow_policy="fixed-sha256-bytes-v1",
    )


__all__ = [
    "COMPILER_BUNDLE_ID",
    # Keep the compiler version component named inside the all contract.
    "COMPILER_VERSION",
    "FEATURE_AVAILABLE",
    "FEATURE_ROW_ID",
    "FEATURE_VALIDITY",
    "FEATURE_VALUES",
    # Keep the label effective component named inside the all contract.
    "LABEL_EFFECTIVE",
    "LABEL_FUTURE_USED",
    "LABEL_ROW_ID",
    "LABEL_VALIDITY",
    "LABEL_VALUE",
    # Keep the model intercept component named inside the all contract.
    "MODEL_INTERCEPT",
    "MODEL_WEIGHTS",
    "PREDICTION_AVAILABLE",
    "PREDICTION_EFFECTIVE",
    "PREDICTION_FEATURE_AVAILABLE",
    # Keep the prediction inference completion component named inside the all contract.
    "PREDICTION_INFERENCE_COMPLETION",
    "PREDICTION_MODEL_CODE",
    "PREDICTION_ROW_ID",
    "PREDICTION_VALIDITY",
    "PREDICTION_VALUE",
    # Keep the schedule availability basis component named inside the all contract.
    "SCHEDULE_AVAILABILITY_BASIS",
    "SCHEDULE_ELIGIBLE_FROM",
    "SCHEDULE_ELIGIBLE_UNTIL",
    "SCHEDULE_MODEL_AVAILABLE",
    "SCHEDULE_MODEL_ID",
    # Keep the schedule training cutoff component named inside the all contract.
    "SCHEDULE_TRAINING_CUTOFF",
    "UNIVERSE_ELIGIBLE_FROM",
    "UNIVERSE_ELIGIBLE_UNTIL",
    "UNIVERSE_ENTITY_ID",
    "UNIVERSE_INPUT_AVAILABLE",
    # Keep the writer bundle id component named inside the all contract.
    "WRITER_BUNDLE_ID",
    "WRITER_SETTINGS_DIGEST",
    "feature_layout",
    "label_layout",
    "model_layout",
    # Keep the prediction layout component named inside the all contract.
    "prediction_layout",
    "schedule_layout",
    "universe_layout",
]
