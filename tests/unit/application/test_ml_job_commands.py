# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from backtest.application.job_commands import resolve_job_command

# Import ml artifacts at the visible module dependency boundary.
from backtest.application.ml_artifacts import (
    BuildFrozenPredictionsRequest,
    FeatureOverlayRow,
    FrozenMissingPolicy,
    LabelOverlayRow,
    # Include publish model schedule request so the ml artifacts dependency remains
    # explicit.
    PublishModelScheduleRequest,
    TrainExactLinearModelRequest,
    UniverseMembershipRow,
)
from backtest.application.ml_contracts import (
    # Include feature spec so the ml contracts dependency remains explicit.
    FeatureSpec,
    ModelCanonicality,
    ModelSchedule,
    ModelScheduleEntry,
    NullPolicy,
    # Include temporal split so the ml contracts dependency remains explicit.
    TemporalSplit,
    TrainingJobSpec,
)
from backtest.application.ml_job_commands import (
    MlJobCommandError,
    # Include resolved build features job so the ml job commands dependency remains
    # explicit.
    ResolvedBuildFeaturesJob,
    ResolvedBuildLabelsJob,
    ResolvedBuildModelScheduleJob,
    ResolvedBuildUniverseJob,
    ResolvedPredictJob,
    # Include resolved train model job so the ml job commands dependency remains explicit.
    ResolvedTrainModelJob,
    resolve_ml_job_command,
    resolved_build_features_job_from_bytes,
    resolved_build_labels_job_from_bytes,
    resolved_build_model_schedule_job_from_bytes,
    # Include resolved build universe job from bytes so the ml job commands dependency
    # remains explicit.
    resolved_build_universe_job_from_bytes,
    resolved_predict_job_from_bytes,
    resolved_train_model_job_from_bytes,
)
from backtest.application.models import JobType

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import (
    ArtifactId,
    BundleId,
    ContentDigest,
    # Include feature set id so the identifiers dependency remains explicit.
    FeatureSetId,
    LabelSetId,
    ModelBundleId,
    ModelScheduleId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
    UniverseId,
)

ResolvedCommand = (
    # Keep the resolved build features job component named inside the resolved command
    # contract.
    ResolvedBuildFeaturesJob
    | ResolvedBuildUniverseJob
    | ResolvedBuildLabelsJob
    | ResolvedTrainModelJob
    | ResolvedBuildModelScheduleJob
    # Keep the resolved predict job component named inside the resolved command contract.
    | ResolvedPredictJob
)


def test_all_phase6_job_codecs_round_trip_and_derive_exact_inputs() -> None:
    # Execute the test all phase6 job codecs round trip and derive exact inputs workflow
    # in explicit, reviewable steps.
    for job_type, command, decoder in _cases():
        # Process _cases() inside the bounded test all phase6 job codecs round trip and
        # derive exact inputs loop.
        payload = command.canonical_bytes()
        decoded = decoder(payload)
        resolved = resolve_ml_job_command(job_type, payload)

        assert decoded == command
        assert resolved.job_type is job_type
        # Verify resolved.canonical_payload == payload before this scenario is accepted.
        assert resolved.canonical_payload == payload
        assert resolved.input_artifact_ids == command.input_artifact_ids
        assert resolved.input_artifact_ids == tuple(
            sorted(resolved.input_artifact_ids, key=lambda item: item.hex)
        )
        # Verify the input artifact ids and resolved relationship before this scenario is
        # accepted.
        assert len(resolved.input_artifact_ids) == len(set(resolved.input_artifact_ids))


def test_shared_durable_job_resolver_accepts_every_phase6_command() -> None:
    # Execute the test shared durable job resolver accepts every phase6 command workflow
    # in explicit, reviewable steps.
    for job_type, command, _ in _cases():
        # Process _cases() inside the bounded test shared durable job resolver accepts
        # every phase6 command loop.
        resolved = resolve_job_command(job_type, command.canonical_bytes())

        assert resolved.job_type is job_type
        assert resolved.canonical_payload == command.canonical_bytes()
        assert resolved.input_artifact_ids == command.input_artifact_ids


def test_large_builder_rows_are_bound_after_transport_and_never_enter_queue_payload() -> None:
    # Execute the test large builder rows are bound after transport and never enter queue
    # payload workflow in explicit, reviewable steps.
    cases = _cases()
    features = cases[0][1]
    universe = cases[1][1]
    labels = cases[2][1]
    assert isinstance(features, ResolvedBuildFeaturesJob)
    # Verify the isinstance, universe and resolved build universe job relationship before
    # this scenario is accepted.
    assert isinstance(universe, ResolvedBuildUniverseJob)
    assert isinstance(labels, ResolvedBuildLabelsJob)
    feature_rows: tuple[FeatureOverlayRow, ...] = ()
    universe_rows: tuple[UniverseMembershipRow, ...] = ()
    label_rows: tuple[LabelOverlayRow, ...] = ()

    # Assemble feature request once so the test large builder rows are bound after
    # transport and never enter queue payload workflow shares one value.
    feature_request = features.publication_request(feature_rows)
    universe_request = universe.publication_request(universe_rows)
    label_request = labels.publication_request(label_rows)

    assert feature_request.rows is feature_rows
    assert universe_request.rows is universe_rows
    # Verify label_request.rows is label_rows before this scenario is accepted.
    assert label_request.rows is label_rows
    for command in (features, universe, labels):
        # Process (features, universe, labels) inside the bounded test large builder rows
        # are bound after transport and never enter queue payload loop.
        document = json.loads(command.canonical_bytes())
        assert "rows" not in document
        assert "path" not in document
        assert "alias" not in document
        assert "payload" not in document


# Apply parametrize semantics to the following test codecs reject noncanonical whitespace
# contract.
@pytest.mark.parametrize("prefix", [b" ", b"\n", b"\t"])
def test_codecs_reject_noncanonical_whitespace(prefix: bytes) -> None:
    # Execute the test codecs reject noncanonical whitespace workflow in explicit,
    # reviewable steps.
    _, command, decoder = _cases()[0]
    with pytest.raises(MlJobCommandError, match="canonical"):
        decoder(prefix + command.canonical_bytes())
    with pytest.raises(MlJobCommandError, match="canonical"):
        decoder(command.canonical_bytes() + prefix)


# Define test codecs reject unsorted json even when semantically equal as one focused
# operation with an explicit boundary.
def test_codecs_reject_unsorted_json_even_when_semantically_equal() -> None:
    # Execute the test codecs reject unsorted json even when semantically equal workflow
    # in explicit, reviewable steps.
    _, command, decoder = _cases()[0]
    document = command.document()
    noncanonical = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    assert noncanonical != command.canonical_bytes()
    with pytest.raises(MlJobCommandError, match="canonical"):
        # Invoke decoder for noncanonical as a visible test codecs reject unsorted json
        # even when semantically equal step.
        decoder(noncanonical)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        # Pass null explicitly so parametrize receives a reviewable payload input in test
        # codecs reject nonobject noninteger and ambiguous json.
        b"null",
        b"[]",
        b"{",
        b'{"value":1.5}',
        b'{"value":NaN}',
        # Pass schema explicitly so parametrize receives a reviewable payload input in
        # test codecs reject nonobject noninteger and ambiguous json.
        b'{"schema":"backtest.build-features-job/v1","schema":"duplicate"}',
    ],
)
def test_codecs_reject_nonobject_noninteger_and_ambiguous_json(payload: bytes) -> None:
    # Execute the test codecs reject nonobject noninteger and ambiguous json workflow in
    # explicit, reviewable steps.
    with pytest.raises(MlJobCommandError):
        resolved_build_features_job_from_bytes(payload)


@pytest.mark.parametrize("forbidden", ["rows", "path", "alias", "config", "payload"])
def test_codecs_reject_extra_opaque_or_location_fields(forbidden: str) -> None:
    # Execute the test codecs reject extra opaque or location fields workflow in explicit,
    # reviewable steps.
    _, command, decoder = _cases()[0]
    document = command.document()
    document[forbidden] = {"anything": "latest"}
    with pytest.raises(MlJobCommandError, match="schema"):
        decoder(canonical_json_bytes(document))


# Define test nested derived id tampering is rejected as one focused operation with an
# explicit boundary.
def test_nested_derived_id_tampering_is_rejected() -> None:
    # Execute the test nested derived id tampering is rejected workflow in explicit,
    # reviewable steps.
    cases = _cases()
    mutations = (
        (cases[0], ("feature_specs", 0, "feature_spec_id")),
        (cases[3], ("training_spec", "training_job_spec_id")),
        (cases[4], ("schedule", "schedule_digest")),
        # Complete the mutations group only after its semantic components are visible.
    )
    for (_, command, decoder), coordinate in mutations:
        # Process mutations inside the bounded test nested derived id tampering is
        # rejected loop.
        document = command.document()
        target: object = document
        for key in coordinate[:-1]:
            # Process coordinate[:-1] inside the bounded test nested derived id tampering
            # is rejected loop.
            if isinstance(key, int):
                # Handle the test nested derived id tampering is rejected isinstance(key,
                # int) branch as a distinct logical block.
                assert isinstance(target, list)
                target = target[key]
            else:
                # Handle the test nested derived id tampering is rejected complement of
                # isinstance(key, int) explicitly.
                assert isinstance(target, dict)
                target = target[key]
        assert isinstance(target, dict)
        target[coordinate[-1]] = _digest("tampered").hex
        with pytest.raises(MlJobCommandError, match="invalid"):
            # Invoke decoder for canonical json bytes and document as a visible test
            # nested derived id tampering is rejected step.
            decoder(canonical_json_bytes(document))


def test_wrong_job_type_and_wrong_schema_fail_closed() -> None:
    # Execute the test wrong job type and wrong schema fail closed workflow in explicit,
    # reviewable steps.
    _, command, _ = _cases()[0]
    with pytest.raises(MlJobCommandError, match="schema"):
        resolve_ml_job_command(JobType.PREDICT, command.canonical_bytes())
    with pytest.raises(MlJobCommandError, match="no Phase-6"):
        resolve_ml_job_command(JobType.RUN_BACKTEST, command.canonical_bytes())

    # Assemble document once so the test wrong job type and wrong schema fail closed
    # workflow shares one value.
    document = command.document()
    document["schema"] = "backtest.build-features-job/v2"
    with pytest.raises(MlJobCommandError, match="unsupported"):
        resolved_build_features_job_from_bytes(canonical_json_bytes(document))


def test_boolean_boundary_and_tolerance_prediction_are_rejected() -> None:
    # Execute the test boolean boundary and tolerance prediction are rejected workflow in
    # explicit, reviewable steps.
    labels = _cases()[2][1]
    assert isinstance(labels, ResolvedBuildLabelsJob)
    label_document = labels.document()
    label_document["training_cutoff"] = True
    with pytest.raises(MlJobCommandError, match="non-negative integer"):
        # Invoke resolved_build_labels_job_from_bytes for canonical json bytes and label
        # document as a visible test boolean boundary and tolerance prediction are
        # rejected step.
        resolved_build_labels_job_from_bytes(canonical_json_bytes(label_document))

    prediction = _cases()[5][1]
    assert isinstance(prediction, ResolvedPredictJob)
    prediction_document = prediction.document()
    prediction_document["canonicality"] = ModelCanonicality.NON_CANONICAL_TOLERANCE.value
    # Acquire raises, ml job command error and pytest at an explicit test boolean boundary
    # and tolerance prediction are rejected context boundary so cleanup remains scoped.
    with pytest.raises(MlJobCommandError, match="invalid"):
        resolved_predict_job_from_bytes(canonical_json_bytes(prediction_document))


def test_order_and_cross_role_duplicate_inputs_are_rejected() -> None:
    # Execute the test order and cross role duplicate inputs are rejected workflow in
    # explicit, reviewable steps.
    features = _cases()[0][1]
    assert isinstance(features, ResolvedBuildFeaturesJob)
    first, second = features.input_feature_set_ids
    document = features.document()
    document["input_feature_set_ids"] = [second.hex, first.hex]
    # Acquire raises, ml job command error and pytest at an explicit test order and cross
    # role duplicate inputs are rejected context boundary so cleanup remains scoped.
    with pytest.raises(MlJobCommandError, match="invalid"):
        resolved_build_features_job_from_bytes(canonical_json_bytes(document))

    prediction = _cases()[5][1]
    assert isinstance(prediction, ResolvedPredictJob)
    duplicate_document = prediction.document()
    # Assemble duplicate document and model schedule id once so the test order and cross
    # role duplicate inputs are rejected workflow shares one value.
    duplicate_document["model_schedule_id"] = prediction.request.feature_set_ids[0].hex
    with pytest.raises(MlJobCommandError, match="unique"):
        resolved_predict_job_from_bytes(canonical_json_bytes(duplicate_document))


def test_schedule_closure_deduplicates_reused_exact_model_without_aliasing() -> None:
    # Execute the test schedule closure deduplicates reused exact model without aliasing
    # workflow in explicit, reviewable steps.
    model = ModelBundleId(_digest("same-model").hex)
    schedule = ModelSchedule(
        (
            ModelScheduleEntry(10, 20, model, 8, 9, "receipt-v1"),
            ModelScheduleEntry(20, 30, model, 18, 19, "receipt-v1"),
            # Complete ModelSchedule only after its receipt-v1 and model schedule entry inputs
            # are visible in test schedule closure deduplicates reused exact model without
            # aliasing.
        )
    )
    command = ResolvedBuildModelScheduleJob(
        PublishModelScheduleRequest(
            schedule,
            # Pass model canonicality explicitly so PublishModelScheduleRequest receives a
            # reviewable numpy-point-in-time-ml-v1 and canonical exact input in test
            # schedule closure deduplicates reused exact model without aliasing.
            ModelCanonicality.CANONICAL_EXACT,
            "numpy-point-in-time-ml-v1",
        )
    )
    assert command.input_artifact_ids == (ArtifactId(model.hex),)


# Define cases as one focused operation with an explicit boundary.
def _cases() -> tuple[tuple[JobType, ResolvedCommand, Callable[[bytes], ResolvedCommand]], ...]:
    # Execute the cases workflow in explicit, reviewable steps.
    feature_ids = _sorted_ids(FeatureSetId, "feature-input-a", "feature-input-b")
    model_ids = _sorted_ids(ModelBundleId, "model-a", "model-b")
    features = tuple(
        sorted(
            (_feature_spec("momentum"), _feature_spec("volume")),
            # Pass key explicitly so sorted receives a reviewable momentum and volume
            # input in cases.
            key=lambda item: item.feature_spec_id.hex,
        )
    )
    training_spec = TrainingJobSpec(
        feature_set_ids=feature_ids,
        # Keep the hex LabelSetId step visible while building training spec.
        label_set_id=LabelSetId(_digest("labels").hex),
        universe_id=UniverseId(_digest("universe").hex),
        split=TemporalSplit(0, 20, 25, 30, 2, 1),
        hyperparameter_digest=_digest("hyperparameters"),
        root_seeds=(7, 11),
        # Pass training cutoff explicitly so TrainingJobSpec receives a reviewable labels
        # and universe input in cases.
        training_cutoff=20,
        modeled_available_boundary=22,
        trainer_bundle_id=BundleId(_digest("trainer").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
    )
    # Assemble schedule once so the cases workflow shares one value.
    schedule = ModelSchedule(
        (
            ModelScheduleEntry(22, 40, model_ids[0], 20, 22, "receipt-v1"),
            ModelScheduleEntry(40, 60, model_ids[1], 38, 39, "modeled-v1"),
        )
        # Complete ModelSchedule only after its receipt-v1 and modeled-v1 inputs are visible
        # in cases.
    )
    commands: tuple[tuple[JobType, ResolvedCommand, Callable[[bytes], ResolvedCommand]], ...] = (
        (
            JobType.BUILD_FEATURES,
            ResolvedBuildFeaturesJob(
                # Register hex through ReplayPackId so the commands table remains
                # scannable.
                ReplayPackId(_digest("replay").hex),
                _digest("replay-semantics"),
                _digest("replay-layout"),
                features,
                feature_ids,
                # Pass numpy-point-in-time-ml-v1 explicitly so ResolvedBuildFeaturesJob
                # receives a reviewable replay and replay-semantics input in cases.
                "numpy-point-in-time-ml-v1",
            ),
            resolved_build_features_job_from_bytes,
        ),
        (
            # Keep the job type component named inside the commands contract.
            JobType.BUILD_UNIVERSE,
            ResolvedBuildUniverseJob(
                SnapshotId(_digest("snapshot").hex),
                _digest("universe-spec"),
                feature_ids,
                # Register hex through BundleId so the commands table remains scannable.
                BundleId(_digest("universe-builder").hex),
                _digest("universe-config"),
                "numpy-point-in-time-ml-v1",
            ),
            resolved_build_universe_job_from_bytes,
            # Complete the commands group only after its semantic components are visible.
        ),
        (
            JobType.BUILD_LABELS,
            ResolvedBuildLabelsJob(
                SnapshotId(_digest("snapshot").hex),
                # Pass training spec explicitly so ResolvedBuildLabelsJob receives a
                # reviewable snapshot and label-spec input in cases.
                training_spec.universe_id,
                _digest("label-spec"),
                BundleId(_digest("label-builder").hex),
                _digest("label-config"),
                20,
                # Pass numpy-point-in-time-ml-v1 explicitly so ResolvedBuildLabelsJob
                # receives a reviewable snapshot and label-spec input in cases.
                "numpy-point-in-time-ml-v1",
            ),
            resolved_build_labels_job_from_bytes,
        ),
        (
            # Keep the job type component named inside the commands contract.
            JobType.TRAIN_MODEL,
            ResolvedTrainModelJob(
                TrainExactLinearModelRequest(
                    training_spec,
                    _digest("feature-schema"),
                    # Register preprocessing through _digest so the commands table remains
                    # scannable.
                    _digest("preprocessing"),
                    _digest("calibration"),
                    1,
                    "exact-rational-linear-v1",
                    ModelCanonicality.CANONICAL_EXACT,
                    # Pass numpy-point-in-time-ml-v1 explicitly so
                    # TrainExactLinearModelRequest receives a reviewable feature-schema
                    # and preprocessing input in cases.
                    "numpy-point-in-time-ml-v1",
                )
            ),
            resolved_train_model_job_from_bytes,
        ),
        # Complete the commands group only after its semantic components are visible.
        (
            JobType.BUILD_MODEL_SCHEDULE,
            ResolvedBuildModelScheduleJob(
                PublishModelScheduleRequest(
                    schedule,
                    # Pass model canonicality explicitly so PublishModelScheduleRequest
                    # receives a reviewable numpy-point-in-time-ml-v1 and canonical exact
                    # input in cases.
                    ModelCanonicality.CANONICAL_EXACT,
                    "numpy-point-in-time-ml-v1",
                )
            ),
            resolved_build_model_schedule_job_from_bytes,
            # Complete the commands group only after its semantic components are visible.
        ),
        (
            JobType.PREDICT,
            ResolvedPredictJob(
                BuildFrozenPredictionsRequest(
                    # Register hex through ReplayPackId so the commands table remains
                    # scannable.
                    ReplayPackId(_digest("replay").hex),
                    _digest("replay-semantics"),
                    _digest("replay-layout"),
                    feature_ids,
                    ModelScheduleId(_digest("schedule").hex),
                    # Pass model ids explicitly so BuildFrozenPredictionsRequest receives
                    # a reviewable replay and replay-semantics input in cases.
                    model_ids,
                    "expected-return",
                    2,
                    FrozenMissingPolicy.REJECT,
                    ModelCanonicality.CANONICAL_EXACT,
                    # Pass numpy-point-in-time-ml-v1 explicitly so
                    # BuildFrozenPredictionsRequest receives a reviewable replay and
                    # replay-semantics input in cases.
                    "numpy-point-in-time-ml-v1",
                )
            ),
            resolved_predict_job_from_bytes,
        ),
        # Complete the commands group only after its semantic components are visible.
    )
    return commands


def _feature_spec(name: str) -> FeatureSpec:
    # Execute the feature spec workflow in explicit, reviewable steps.
    return FeatureSpec(
        name=name,
        version=1,
        entity_key="replay_row_id",
        input_ids=tuple(sorted((_digest("source-a"), _digest("source-b")))),
        # Pass effective time semantics explicitly so FeatureSpec receives a reviewable
        # replay row id and source-a input in feature spec.
        effective_time_semantics="event-boundary-v1",
        available_time_semantics="next-boundary-v1",
        warmup_boundaries=2,
        dtype="<i8",
        null_policy=NullPolicy.EXPLICIT_BITMAP,
        # Include code bundle id in the completed feature spec result.
        code_bundle_id=BundleId(_digest(f"feature:{name}").hex),
        runtime_lock_id=RuntimeLockId(_digest("runtime").hex),
    )


def _sorted_ids[T: ContentDigest](kind: type[T], *labels: str) -> tuple[T, ...]:
    return tuple(sorted((kind(_digest(label).hex) for label in labels), key=lambda item: item.hex))


# Define digest as one focused operation with an explicit boundary.
def _digest(label: str) -> ContentDigest:
    return domain_digest("test.ml-job", {"label": label})
