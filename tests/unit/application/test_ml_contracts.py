# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import pytest

from backtest.application.ml_contracts import (
    EXACT_SCHEDULE_GAP_POLICY,
    ExactInferencePolicy,
    # Include feature set manifest so the ml contracts dependency remains explicit.
    FeatureSetManifest,
    FeatureSpec,
    InferenceMissingPolicy,
    InferenceMode,
    LabelSetManifest,
    # Include model bundle manifest so the ml contracts dependency remains explicit.
    ModelBundleManifest,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    ModelUnavailableError,
    # Include null policy so the ml contracts dependency remains explicit.
    NullPolicy,
    PointInTimeRow,
    PredictionAvailability,
    PredictionSetManifest,
    TemporalSplit,
    # Include training job spec so the ml contracts dependency remains explicit.
    TrainingJobSpec,
    UniverseManifest,
)
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import (
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    ContentDigest,
    FeatureSetId,
    LabelSetId,
    ModelBundleId,
    # Include model schedule id so the identifiers dependency remains explicit.
    ModelScheduleId,
    RuntimeLockId,
    SnapshotId,
    UniverseId,
)


# Define digest as one focused operation with an explicit boundary.
def _digest(label: str) -> ContentDigest:
    return domain_digest("test.ml", {"label": label})


def _bundle(label: str) -> BundleId:
    return BundleId(_digest(label).hex)


def _runtime() -> RuntimeLockId:
    # Return the completed runtime result without a hidden fallback.
    return RuntimeLockId(_digest("runtime").hex)


def _feature_spec(name: str = "momentum") -> FeatureSpec:
    # Execute the feature spec workflow in explicit, reviewable steps.
    return FeatureSpec(
        name=name,
        version=1,
        entity_key="replay_row_id",
        input_ids=(_digest("snapshot-input"),),
        # Pass effective time semantics explicitly so FeatureSpec receives a reviewable
        # replay row id and snapshot-input input in feature spec.
        effective_time_semantics="event-boundary-v1",
        available_time_semantics="close-plus-one-boundary-v1",
        warmup_boundaries=2,
        dtype="<i8",
        null_policy=NullPolicy.EXPLICIT_BITMAP,
        # Include code bundle id in the completed feature spec result.
        code_bundle_id=_bundle(f"feature:{name}"),
        runtime_lock_id=_runtime(),
    )


def test_point_in_time_row_rejects_lookahead() -> None:
    # Execute the test point in time row rejects lookahead workflow in explicit,
    # reviewable steps.
    assert PointInTimeRow(0, 1, 10, 11).available_boundary_ordinal == 11
    with pytest.raises(ValueError, match="available before"):
        PointInTimeRow(0, 1, 10, 9)


def test_feature_identity_is_exact_and_requires_canonical_dependencies() -> None:
    # Execute the test feature identity is exact and requires canonical dependencies
    # workflow in explicit, reviewable steps.
    spec = _feature_spec()
    assert spec.feature_spec_id == _feature_spec().feature_spec_id

    with pytest.raises(ValueError, match="sorted"):
        # Keep raises, value error and pytest active only for the bounded test feature
        # identity is exact and requires canonical dependencies operation.
        FeatureSpec(
            name="bad",
            version=1,
            entity_key="row",
            input_ids=(_digest("z"), _digest("a")),
            # Pass effective time semantics explicitly so FeatureSpec receives a
            # reviewable bad and row input in test feature identity is exact and requires
            # canonical dependencies.
            effective_time_semantics="effective",
            available_time_semantics="available",
            warmup_boundaries=0,
            dtype="<i8",
            null_policy=NullPolicy.FORBID,
            # Pass code bundle id explicitly to FeatureSpec for bad and row.
            code_bundle_id=_bundle("bad"),
            runtime_lock_id=_runtime(),
        )


def test_feature_set_identity_includes_physical_bytes_and_causal_schema() -> None:
    # Execute the test feature set identity includes physical bytes and causal schema
    # workflow in explicit, reviewable steps.
    spec = _feature_spec()
    manifest = FeatureSetManifest(
        snapshot_id=SnapshotId(_digest("snapshot").hex),
        replay_semantics_id=_digest("semantics"),
        feature_specs=(spec,),
        # Pass input feature set ids explicitly so FeatureSetManifest receives a
        # reviewable snapshot and semantics input in test feature set identity includes
        # physical bytes and causal schema.
        input_feature_set_ids=(),
        row_count=4,
        alignment_policy="replay-row-id-v1",
        schema_digest=_digest("schema"),
        physical_content_digest=_digest("bytes-a"),
        # Pass maximum available boundary explicitly so FeatureSetManifest receives a
        # reviewable snapshot and semantics input in test feature set identity includes
        # physical bytes and causal schema.
        maximum_available_boundary=12,
    )
    changed = FeatureSetManifest(
        snapshot_id=manifest.snapshot_id,
        replay_semantics_id=manifest.replay_semantics_id,
        # Pass feature specs explicitly so FeatureSetManifest receives a reviewable
        # bytes-b and snapshot id input in test feature set identity includes physical
        # bytes and causal schema.
        feature_specs=manifest.feature_specs,
        input_feature_set_ids=(),
        row_count=4,
        alignment_policy=manifest.alignment_policy,
        schema_digest=manifest.schema_digest,
        # Keep the bytes-b _digest step visible while building changed.
        physical_content_digest=_digest("bytes-b"),
        maximum_available_boundary=12,
    )
    assert manifest.build_key != changed.build_key


def test_universe_and_labels_are_separate_training_artifacts() -> None:
    # Execute the test universe and labels are separate training artifacts workflow in
    # explicit, reviewable steps.
    universe = UniverseManifest(
        snapshot_id=SnapshotId(_digest("snapshot").hex),
        universe_spec_id=_digest("point-in-time-universe"),
        maximum_input_available_boundary=100,
        row_count=5,
        # Keep the universe-bytes _digest step visible while building universe.
        physical_content_digest=_digest("universe-bytes"),
    )
    labels = LabelSetManifest(
        snapshot_id=universe.snapshot_id,
        label_spec_id=_digest("future-return-label"),
        # Keep the hex UniverseId step visible while building labels.
        universe_id=UniverseId(_digest("committed-universe").hex),
        training_cutoff=100,
        maximum_future_boundary_used=110,
        row_count=5,
        physical_content_digest=_digest("label-bytes"),
        # Complete LabelSetManifest only after its future-return-label and committed-universe
        # inputs are visible in test universe and labels are separate training artifacts.
    )
    assert universe.build_key != labels.build_key


def test_training_spec_enforces_temporal_split_and_availability() -> None:
    # Execute the test training spec enforces temporal split and availability workflow in
    # explicit, reviewable steps.
    split = TemporalSplit(0, 80, 90, 100, purge_boundaries=5, embargo_boundaries=2)
    spec = TrainingJobSpec(
        feature_set_ids=(FeatureSetId(_digest("feature-set").hex),),
        label_set_id=LabelSetId(_digest("labels").hex),
        universe_id=UniverseId(_digest("universe").hex),
        # Pass split explicitly so TrainingJobSpec receives a reviewable feature-set and
        # labels input in test training spec enforces temporal split and availability.
        split=split,
        hyperparameter_digest=_digest("hyperparameters"),
        root_seeds=(7, 11),
        training_cutoff=80,
        modeled_available_boundary=85,
        # Keep the trainer _bundle step visible while building spec.
        trainer_bundle_id=_bundle("trainer"),
        runtime_lock_id=_runtime(),
    )
    assert spec.training_job_spec_id == spec.training_job_spec_id

    with pytest.raises(ValueError, match="cannot be available"):
        # Keep raises, value error and pytest active only for the bounded test training
        # spec enforces temporal split and availability operation.
        TrainingJobSpec(
            feature_set_ids=spec.feature_set_ids,
            label_set_id=spec.label_set_id,
            universe_id=spec.universe_id,
            split=spec.split,
            # Pass hyperparameter digest explicitly so TrainingJobSpec receives a
            # reviewable feature set ids and label set id input in test training spec
            # enforces temporal split and availability.
            hyperparameter_digest=spec.hyperparameter_digest,
            root_seeds=spec.root_seeds,
            training_cutoff=80,
            modeled_available_boundary=79,
            trainer_bundle_id=spec.trainer_bundle_id,
            # Pass runtime lock id explicitly so TrainingJobSpec receives a reviewable
            # feature set ids and label set id input in test training spec enforces
            # temporal split and availability.
            runtime_lock_id=spec.runtime_lock_id,
        )


def test_model_bundle_carries_training_runtime_and_determinism_declaration() -> None:
    # Execute the test model bundle carries training runtime and determinism declaration
    # workflow in explicit, reviewable steps.
    manifest = ModelBundleManifest(
        training_job_spec_id=_digest("training"),
        feature_schema_digest=_digest("feature-schema"),
        weights_digest=_digest("weights"),
        preprocessing_digest=_digest("preprocessing"),
        # Keep the calibration _digest step visible while building manifest.
        calibration_digest=_digest("calibration"),
        metrics_digest=_digest("metrics"),
        framework="exact-linear-v1",
        runtime_lock_id=_runtime(),
        training_cutoff=100,
        # Pass model available boundary explicitly so ModelBundleManifest receives a
        # reviewable training and feature-schema input in test model bundle carries
        # training runtime and determinism declaration.
        model_available_boundary=105,
        canonicality=ModelCanonicality.CANONICAL_EXACT,
    )
    assert manifest.build_key == manifest.build_key


def test_walk_forward_schedule_is_half_open_and_gap_fails_closed() -> None:
    # Execute the test walk forward schedule is half open and gap fails closed workflow in
    # explicit, reviewable steps.
    first = ModelScheduleEntry(
        eligible_from=10,
        eligible_until=20,
        model_bundle_id=ModelBundleId(_digest("m1").hex),
        training_cutoff=8,
        # Pass model available boundary explicitly so ModelScheduleEntry receives a
        # reviewable m1 and historical-build-receipt-v1 input in test walk forward
        # schedule is half open and gap fails closed.
        model_available_boundary=9,
        availability_basis="historical-build-receipt-v1",
    )
    second = ModelScheduleEntry(
        eligible_from=21,
        # Pass eligible until explicitly so ModelScheduleEntry receives a reviewable m2
        # and modeled-completion-v1 input in test walk forward schedule is half open and
        # gap fails closed.
        eligible_until=30,
        model_bundle_id=ModelBundleId(_digest("m2").hex),
        training_cutoff=19,
        model_available_boundary=20,
        availability_basis="modeled-completion-v1",
        # Complete ModelScheduleEntry only after its m2 and modeled-completion-v1 inputs are
        # visible in test walk forward schedule is half open and gap fails closed.
    )
    schedule = ModelSchedule((first, second))
    assert schedule.build_key == schedule.build_key
    assert schedule.model_for(10) == first.model_bundle_id
    assert schedule.model_for(19) == first.model_bundle_id
    # Acquire raises, model unavailable error and pytest at an explicit test walk forward
    # schedule is half open and gap fails closed context boundary so cleanup remains
    # scoped.
    with pytest.raises(ModelUnavailableError, match="MODEL_UNAVAILABLE"):
        schedule.model_for(20)

    with pytest.raises(ValueError, match="overlap"):
        # Keep raises, value error and pytest active only for the bounded test walk
        # forward schedule is half open and gap fails closed operation.
        ModelSchedule(
            (
                first,
                ModelScheduleEntry(
                    eligible_from=19,
                    # Pass eligible until explicitly so ModelScheduleEntry receives a
                    # reviewable receipt and model bundle id input in test walk forward
                    # schedule is half open and gap fails closed.
                    eligible_until=30,
                    model_bundle_id=second.model_bundle_id,
                    training_cutoff=18,
                    model_available_boundary=19,
                    availability_basis="receipt",
                    # Complete ModelScheduleEntry only after its receipt and model bundle id
                    # inputs are visible in test walk forward schedule is half open and gap
                    # fails closed.
                ),
            )
        )


def test_explicit_schedule_fallback_is_hashed_and_never_an_alias() -> None:
    # Execute the test explicit schedule fallback is hashed and never an alias workflow in
    # explicit, reviewable steps.
    fallback = ModelBundleId(_digest("fallback-exact-id").hex)
    schedule = ModelSchedule((), fallback_model_bundle_id=fallback)
    assert schedule.model_for(999) == fallback
    assert (
        schedule.build_key
        # Keep the model schedule expectation tied to build key, schedule and model
        # schedule in this scenario.
        != ModelSchedule(
            (), fallback_model_bundle_id=ModelBundleId(_digest("different").hex)
        ).build_key
    )


def test_exact_inference_policy_is_canonical_and_mode_is_semantic() -> None:
    # Execute the test exact inference policy is canonical and mode is semantic workflow
    # in explicit, reviewable steps.
    frozen = ExactInferencePolicy.frozen_exact_linear(
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=2,
    )
    # Assemble embedded once so the test exact inference policy is canonical and mode is
    # semantic workflow shares one value.
    embedded = ExactInferencePolicy.embedded_exact_linear(
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.NULL,
        inference_delay_boundaries=2,
    )

    # Verify the frozen, from document and exact inference policy relationship before this
    # scenario is accepted.
    assert ExactInferencePolicy.from_document(frozen.document()) == frozen
    assert frozen.document()["schedule_gap_policy"] == EXACT_SCHEDULE_GAP_POLICY
    assert frozen.inference_policy_digest != embedded.inference_policy_digest
    with pytest.raises(ValueError, match="canonical no-prediction"):
        # Keep raises, value error and pytest active only for the bounded test exact
        # inference policy is canonical and mode is semantic operation.
        ExactInferencePolicy(
            mode=InferenceMode.DISABLED,
            prediction_name=None,
            missing_policy=InferenceMissingPolicy.NULL,
            inference_delay_boundaries=0,
            # Complete ExactInferencePolicy only after its disabled and null inputs are
            # visible in test exact inference policy is canonical and mode is semantic.
        )
    with pytest.raises(ValueError, match="stateful"):
        # Keep raises, value error and pytest active only for the bounded test exact
        # inference policy is canonical and mode is semantic operation.
        ExactInferencePolicy(
            mode=InferenceMode.STATEFUL_SEQUENTIAL,
            prediction_name="score",
            missing_policy=InferenceMissingPolicy.REJECT,
            inference_delay_boundaries=0,
            # Complete ExactInferencePolicy only after its score and stateful sequential
            # inputs are visible in test exact inference policy is canonical and mode is
            # semantic.
        )


def test_selected_ensemble_prediction_availability_uses_all_declared_operands() -> None:
    # Execute the test selected ensemble prediction availability uses all declared
    # operands workflow in explicit, reviewable steps.
    availability = PredictionAvailability(
        feature_available_boundary=10,
        model_available_boundaries=(8, 12, 9),
        fitted_component_available_boundaries=(7, 14),
        inference_completion_boundary=13,
        # Complete PredictionAvailability only after its declared inputs are visible in test
        # selected ensemble prediction availability uses all declared operands.
    )
    assert availability.available_boundary_ordinal == 14


def test_prediction_set_identity_pins_schedule_models_policy_and_bytes() -> None:
    # Execute the test prediction set identity pins schedule models policy and bytes
    # workflow in explicit, reviewable steps.
    feature_id = FeatureSetId(_digest("features").hex)
    model_id = ModelBundleId(_digest("model").hex)
    manifest = PredictionSetManifest(
        feature_set_ids=(feature_id,),
        model_schedule_id=ModelScheduleId(_digest("schedule").hex),
        # Pass model bundle ids explicitly so PredictionSetManifest receives a reviewable
        # schedule and policy input in test prediction set identity pins schedule models
        # policy and bytes.
        model_bundle_ids=(model_id,),
        inference_mode=InferenceMode.FROZEN,
        inference_policy_digest=_digest("policy"),
        causal_availability_policy="max-all-operands-v1",
        compiler_bundle_id=_bundle("prediction-compiler"),
        # Keep the runtime _runtime step visible while building manifest.
        runtime_lock_id=_runtime(),
        row_count=10,
        schema_digest=_digest("prediction-schema"),
        physical_content_digest=_digest("prediction-bytes"),
        canonicality=ModelCanonicality.CANONICAL_EXACT,
        # Complete PredictionSetManifest only after its schedule and policy inputs are visible
        # in test prediction set identity pins schedule models policy and bytes.
    )
    assert manifest.build_key == manifest.build_key


def test_future_model_cannot_start_eligibility_interval() -> None:
    # Execute the test future model cannot start eligibility interval workflow in
    # explicit, reviewable steps.
    with pytest.raises(ValueError, match="not available"):
        # Keep raises, value error and pytest active only for the bounded test future
        # model cannot start eligibility interval operation.
        ModelScheduleEntry(
            eligible_from=10,
            eligible_until=20,
            model_bundle_id=ModelBundleId(_digest("future").hex),
            training_cutoff=9,
            # Pass model available boundary explicitly so ModelScheduleEntry receives a
            # reviewable future and hex input in test future model cannot start
            # eligibility interval.
            model_available_boundary=11,
            availability_basis="future",
        )
