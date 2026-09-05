# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backtest.application.ml_artifacts import (
    # Include build frozen predictions request so the ml artifacts dependency remains
    # explicit.
    BuildFrozenPredictionsRequest,
    FrozenMissingPolicy,
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
)

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import (
    FeatureSpec,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    # Include null policy so the ml contracts dependency remains explicit.
    NullPolicy,
    TemporalSplit,
    TrainingJobSpec,
)
from backtest.application.ml_job_commands import (
    # Include resolved build features job so the ml job commands dependency remains
    # explicit.
    ResolvedBuildFeaturesJob,
    ResolvedBuildLabelsJob,
    ResolvedBuildModelScheduleJob,
    ResolvedBuildUniverseJob,
    ResolvedPredictJob,
    # Include resolved train model job so the ml job commands dependency remains explicit.
    ResolvedTrainModelJob,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    BundleId,
    # Include content digest so the identifiers dependency remains explicit.
    ContentDigest,
    FeatureSetId,
    LabelSetId,
    ModelBundleId,
    ModelScheduleId,
    # Include replay pack id so the identifiers dependency remains explicit.
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
    UniverseId,
)

# Import ml schemas at the visible module dependency boundary.
from backtest.interfaces.api.ml_schemas import (
    BuildFeaturesJobForm,
    BuildLabelsJobForm,
    BuildModelScheduleJobForm,
    BuildUniverseJobForm,
    # Include predict job form so the ml schemas dependency remains explicit.
    PredictJobForm,
    TrainModelJobForm,
)


def test_all_ml_api_forms_round_trip_exact_domain_commands_and_json() -> None:
    # Execute the test all ml api forms round trip exact domain commands and json workflow
    # in explicit, reviewable steps.
    features, universe, labels, train, schedule, predict = _commands()

    feature_form = BuildFeaturesJobForm.from_domain(features)
    universe_form = BuildUniverseJobForm.from_domain(universe)
    labels_form = BuildLabelsJobForm.from_domain(labels)
    train_form = TrainModelJobForm.from_domain(train)
    # Assemble schedule form once so the test all ml api forms round trip exact domain
    # commands and json workflow shares one value.
    schedule_form = BuildModelScheduleJobForm.from_domain(schedule)
    predict_form = PredictJobForm.from_domain(predict)

    assert feature_form.to_domain() == features
    assert universe_form.to_domain() == universe
    assert labels_form.to_domain() == labels
    # Verify train_form.to_domain() == train before this scenario is accepted.
    assert train_form.to_domain() == train
    assert schedule_form.to_domain() == schedule
    assert predict_form.to_domain() == predict

    assert (
        BuildFeaturesJobForm.model_validate_json(feature_form.model_dump_json()).to_domain()
        # Keep the features expectation tied to features, to domain and model validate
        # json in this scenario.
        == features
    )
    assert (
        BuildUniverseJobForm.model_validate_json(universe_form.model_dump_json()).to_domain()
        == universe
        # Verify the universe, to domain and model validate json relationship before this
        # scenario is accepted.
    )
    assert (
        BuildLabelsJobForm.model_validate_json(labels_form.model_dump_json()).to_domain() == labels
    )
    assert TrainModelJobForm.model_validate_json(train_form.model_dump_json()).to_domain() == train
    # Verify the schedule, to domain and model validate json relationship before this
    # scenario is accepted.
    assert (
        BuildModelScheduleJobForm.model_validate_json(schedule_form.model_dump_json()).to_domain()
        == schedule
    )
    assert PredictJobForm.model_validate_json(predict_form.model_dump_json()).to_domain() == predict


# Define test forms emit only typed fields and never large rows or generic payloads as one
# focused operation with an explicit boundary.
def test_forms_emit_only_typed_fields_and_never_large_rows_or_generic_payloads() -> None:
    # Execute the test forms emit only typed fields and never large rows or generic
    # payloads workflow in explicit, reviewable steps.
    features, universe, labels, *_ = _commands()
    for form in (
        BuildFeaturesJobForm.from_domain(features),
        BuildUniverseJobForm.from_domain(universe),
        BuildLabelsJobForm.from_domain(labels),
        # Traverse from domain, features and universe explicitly so each test forms emit only
        # typed fields and never large rows or generic payloads iteration remains traceable.
    ):
        # Process from domain, features and universe inside the bounded test forms emit
        # only typed fields and never large rows or generic payloads loop.
        document = json.loads(form.model_dump_json())
        assert "rows" not in document
        assert "path" not in document
        assert "alias" not in document
        assert "payload" not in document
        # Verify 'config' not in document before this scenario is accepted.
        assert "config" not in document


@pytest.mark.parametrize("field", ["rows", "path", "alias", "payload", "config"])
def test_feature_form_rejects_opaque_extra_fields(field: str) -> None:
    # Execute the test feature form rejects opaque extra fields workflow in explicit,
    # reviewable steps.
    features = _commands()[0]
    document = json.loads(BuildFeaturesJobForm.from_domain(features).model_dump_json())
    document[field] = {"arbitrary": "latest"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BuildFeaturesJobForm.model_validate_json(canonical_json_bytes(document))


# Apply parametrize semantics to the following test forms reject alias path uppercase and
# wrong length ids contract.
@pytest.mark.parametrize("value", ["latest", "/tmp/model.npy", "A" * 64, "0" * 63])
def test_forms_reject_alias_path_uppercase_and_wrong_length_ids(value: str) -> None:
    # Execute the test forms reject alias path uppercase and wrong length ids workflow in
    # explicit, reviewable steps.
    prediction = _commands()[5]
    document = json.loads(PredictJobForm.from_domain(prediction).model_dump_json())
    document["model_schedule_id"] = value
    with pytest.raises(ValidationError):
        PredictJobForm.model_validate_json(canonical_json_bytes(document))


# Define test forms reject wrong version unsorted ids and duplicates as one focused
# operation with an explicit boundary.
def test_forms_reject_wrong_version_unsorted_ids_and_duplicates() -> None:
    # Execute the test forms reject wrong version unsorted ids and duplicates workflow in
    # explicit, reviewable steps.
    features = _commands()[0]
    document = json.loads(BuildFeaturesJobForm.from_domain(features).model_dump_json())
    document["spec_version"] = 2
    with pytest.raises(ValidationError):
        BuildFeaturesJobForm.model_validate_json(canonical_json_bytes(document))

    # Assemble first once so the test forms reject wrong version unsorted ids and
    # duplicates workflow shares one value.
    first = _digest("feature-z").hex
    second = _digest("feature-a").hex
    document = json.loads(BuildFeaturesJobForm.from_domain(features).model_dump_json())
    document["input_feature_set_ids"] = sorted((first, second), reverse=True)
    with pytest.raises(ValidationError, match="must be sorted"):
        # Invoke model_validate_json for canonical json bytes and document as a visible
        # test forms reject wrong version unsorted ids and duplicates step.
        BuildFeaturesJobForm.model_validate_json(canonical_json_bytes(document))

    document["input_feature_set_ids"] = [first, first]
    with pytest.raises(ValidationError, match="must be unique"):
        BuildFeaturesJobForm.model_validate_json(canonical_json_bytes(document))


def test_forms_reject_bool_as_integer_and_noncanonical_ml_mode() -> None:
    # Execute the test forms reject bool as integer and noncanonical ml mode workflow in
    # explicit, reviewable steps.
    labels = _commands()[2]
    label_document = json.loads(BuildLabelsJobForm.from_domain(labels).model_dump_json())
    label_document["training_cutoff"] = True
    with pytest.raises(ValidationError):
        BuildLabelsJobForm.model_validate_json(canonical_json_bytes(label_document))

    # Assemble train once so the test forms reject bool as integer and noncanonical ml
    # mode workflow shares one value.
    train = _commands()[3]
    train_document = json.loads(TrainModelJobForm.from_domain(train).model_dump_json())
    train_document["canonicality"] = ModelCanonicality.NON_CANONICAL_TOLERANCE.value
    with pytest.raises(ValidationError, match="exact integer trainer"):
        TrainModelJobForm.model_validate_json(canonical_json_bytes(train_document))

    # Assemble predict once so the test forms reject bool as integer and noncanonical ml
    # mode workflow shares one value.
    predict = _commands()[5]
    predict_document = json.loads(PredictJobForm.from_domain(predict).model_dump_json())
    predict_document["canonicality"] = ModelCanonicality.NON_CANONICAL_TOLERANCE.value
    with pytest.raises(ValidationError, match="exact frozen builder"):
        PredictJobForm.model_validate_json(canonical_json_bytes(predict_document))


# Define test forms enforce point in time and temporal cross field invariants as one
# focused operation with an explicit boundary.
def test_forms_enforce_point_in_time_and_temporal_cross_field_invariants() -> None:
    # Execute the test forms enforce point in time and temporal cross field invariants
    # workflow in explicit, reviewable steps.
    features = _commands()[0]
    feature_document = json.loads(BuildFeaturesJobForm.from_domain(features).model_dump_json())
    feature_document["feature_specs"][0]["entity_key"] = "latest-token-alias"
    with pytest.raises(ValidationError, match="align to replay_row_id"):
        BuildFeaturesJobForm.model_validate_json(canonical_json_bytes(feature_document))

    # Assemble train once so the test forms enforce point in time and temporal cross field
    # invariants workflow shares one value.
    train = _commands()[3]
    train_document = json.loads(TrainModelJobForm.from_domain(train).model_dump_json())
    train_document["training_spec"]["modeled_available_boundary"] = 10
    with pytest.raises(ValidationError, match="before its training cutoff"):
        TrainModelJobForm.model_validate_json(canonical_json_bytes(train_document))

    # Assemble schedule once so the test forms enforce point in time and temporal cross
    # field invariants workflow shares one value.
    schedule = _commands()[4]
    schedule_document = json.loads(
        BuildModelScheduleJobForm.from_domain(schedule).model_dump_json()
    )
    schedule_document["schedule"]["entries"][1]["eligible_from"] = 29
    # Acquire raises, validation error and pytest at an explicit test forms enforce point
    # in time and temporal cross field invariants context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValidationError, match="overlap"):
        BuildModelScheduleJobForm.model_validate_json(canonical_json_bytes(schedule_document))


def test_forms_reject_nul_tokens_and_nested_unknown_fields() -> None:
    # Execute the test forms reject nul tokens and nested unknown fields workflow in
    # explicit, reviewable steps.
    prediction = _commands()[5]
    document = json.loads(PredictJobForm.from_domain(prediction).model_dump_json())
    document["prediction_name"] = "prediction\u0000name"
    with pytest.raises(ValidationError, match="NUL-free"):
        PredictJobForm.model_validate_json(canonical_json_bytes(document))

    # Assemble train once so the test forms reject nul tokens and nested unknown fields
    # workflow shares one value.
    train = _commands()[3]
    train_document = json.loads(TrainModelJobForm.from_domain(train).model_dump_json())
    train_document["training_spec"]["trainer_path"] = "/tmp/trainer.py"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TrainModelJobForm.model_validate_json(canonical_json_bytes(train_document))


# Define commands as one focused operation with an explicit boundary.
def _commands() -> tuple[
    ResolvedBuildFeaturesJob,
    ResolvedBuildUniverseJob,
    ResolvedBuildLabelsJob,
    ResolvedTrainModelJob,
    # Keep the resolved build model schedule job input explicit in the commands contract.
    ResolvedBuildModelScheduleJob,
    ResolvedPredictJob,
]:
    # Execute the commands workflow in explicit, reviewable steps.
    feature_id = FeatureSetId(_digest("features").hex)
    model_id = ModelBundleId(_digest("model").hex)
    universe_id = UniverseId(_digest("universe").hex)
    feature = FeatureSpec(
        name="momentum",
        # Pass version explicitly so FeatureSpec receives a reviewable momentum and replay
        # row id input in commands.
        version=1,
        entity_key="replay_row_id",
        input_ids=(_digest("source-input"),),
        effective_time_semantics="event-boundary-v1",
        available_time_semantics="next-boundary-v1",
        # Pass warmup boundaries explicitly so FeatureSpec receives a reviewable momentum
        # and replay row id input in commands.
        warmup_boundaries=2,
        dtype="<i8",
        null_policy=NullPolicy.EXPLICIT_BITMAP,
        code_bundle_id=BundleId(_digest("feature-bundle").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
        # Complete FeatureSpec only after its momentum and replay row id inputs are visible in
        # commands.
    )
    training_spec = TrainingJobSpec(
        feature_set_ids=(feature_id,),
        label_set_id=LabelSetId(_digest("labels").hex),
        universe_id=universe_id,
        # Keep the temporal split TemporalSplit step visible while building training spec.
        split=TemporalSplit(0, 20, 25, 30, 2, 1),
        hyperparameter_digest=_digest("hyperparameters"),
        root_seeds=(7,),
        training_cutoff=20,
        modeled_available_boundary=22,
        # Keep the hex BundleId step visible while building training spec.
        trainer_bundle_id=BundleId(_digest("trainer").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
    )
    schedule = ModelSchedule(
        (
            # Keep the model schedule entry and model id ModelScheduleEntry step visible
            # while building schedule.
            ModelScheduleEntry(22, 30, model_id, 20, 22, "receipt-v1"),
            ModelScheduleEntry(30, 40, model_id, 28, 29, "modeled-v1"),
        )
    )
    replay_id = ReplayPackId(_digest("replay").hex)
    # Assemble semantics id once so the commands workflow shares one value.
    semantics_id = _digest("semantics")
    layout_id = _digest("layout")
    compiler = "numpy-point-in-time-ml-v1"
    return (
        ResolvedBuildFeaturesJob(
            # Pass replay id explicitly so ResolvedBuildFeaturesJob receives a reviewable
            # replay id and semantics id input in commands.
            replay_id,
            semantics_id,
            layout_id,
            (feature,),
            (feature_id,),
            # Pass compiler explicitly so ResolvedBuildFeaturesJob receives a reviewable
            # replay id and semantics id input in commands.
            compiler,
        ),
        ResolvedBuildUniverseJob(
            SnapshotId(_digest("snapshot").hex),
            _digest("universe-spec"),
            # Open the snapshot and universe-spec payload explicitly for
            # ResolvedBuildUniverseJob within commands.
            (feature_id,),
            BundleId(_digest("universe-builder").hex),
            _digest("universe-config"),
            compiler,
        ),
        # Include resolved build labels job in the completed commands result.
        ResolvedBuildLabelsJob(
            SnapshotId(_digest("snapshot").hex),
            universe_id,
            _digest("label-spec"),
            BundleId(_digest("label-builder").hex),
            # Include digest in the completed commands result.
            _digest("label-config"),
            20,
            compiler,
        ),
        ResolvedTrainModelJob(
            # Include train exact linear model request in the completed commands result.
            TrainExactLinearModelRequest(
                training_spec,
                _digest("feature-schema"),
                _digest("preprocessing"),
                _digest("calibration"),
                # Keep train exact linear model request, training spec and exact-rational-
                # linear-v1 visible while completing TrainExactLinearModelRequest within
                # commands.
                1,
                "exact-rational-linear-v1",
                ModelCanonicality.CANONICAL_EXACT,
                compiler,
            )
            # Complete ResolvedTrainModelJob only after its exact-rational-linear-v1 and
            # feature-schema inputs are visible in commands.
        ),
        ResolvedBuildModelScheduleJob(
            PublishModelScheduleRequest(
                schedule,
                ModelCanonicality.CANONICAL_EXACT,
                # Pass compiler explicitly so PublishModelScheduleRequest receives a
                # reviewable canonical exact and schedule input in commands.
                compiler,
            )
        ),
        ResolvedPredictJob(
            BuildFrozenPredictionsRequest(
                # Pass replay id explicitly so BuildFrozenPredictionsRequest receives a
                # reviewable schedule and expected-return input in commands.
                replay_id,
                semantics_id,
                layout_id,
                (feature_id,),
                ModelScheduleId(_digest("schedule").hex),
                # Open the schedule and expected-return payload explicitly for
                # BuildFrozenPredictionsRequest within commands.
                (model_id,),
                "expected-return",
                2,
                FrozenMissingPolicy.REJECT,
                ModelCanonicality.CANONICAL_EXACT,
                # Pass compiler explicitly so BuildFrozenPredictionsRequest receives a
                # reviewable schedule and expected-return input in commands.
                compiler,
            )
        ),
    )


def _digest(label: str) -> ContentDigest:
    # Return the completed digest result without a hidden fallback.
    return domain_digest("test.ml-api", {"label": label})
