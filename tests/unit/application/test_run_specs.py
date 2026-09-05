# Declare this module's dependencies and contracts before execution.
from __future__ import annotations

import json

import pytest

from backtest.application.errors import ErrorCode, ReprepareRequiredError
from backtest.application.job_commands import run_input_artifact_ids

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import ExactInferencePolicy, InferenceMissingPolicy
from backtest.application.run_results import RunBackend, RunPhysicalSettings
from backtest.application.run_specs import (
    AssetBalance,
    ReplayInputFormat,
    # Include resolved component so the run specs dependency remains explicit.
    ResolvedComponent,
    ResolvedReplayInput,
    ResolvedRunSpec,
    resolved_run_spec_bytes,
    resolved_run_spec_from_bytes,
    # Close the run specs import after its required symbols are visible.
)
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    ArtifactId,
    AssetId,
    BundleId,
    ContentDigest,
    # Include dataset revision id so the identifiers dependency remains explicit.
    DatasetRevisionId,
    FeatureSetId,
    LogicalContentHash,
    ModelScheduleId,
    NetworkId,
    # Include prediction set id so the identifiers dependency remains explicit.
    PredictionSetId,
    ReplayPackId,
    RuntimeLockId,
    SnapshotId,
)


# Define test resolved run document round trips and detects tampering as one focused
# operation with an explicit boundary.
def test_resolved_run_document_round_trips_and_detects_tampering() -> None:
    # Execute the test resolved run document round trips and detects tampering workflow in
    # explicit, reviewable steps.
    spec = _spec(ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET))
    payload = resolved_run_spec_bytes(spec)

    assert resolved_run_spec_from_bytes(payload) == spec

    tampered = json.loads(payload)
    tampered["root_seed"] = 43
    # Acquire raises, value error and pytest at an explicit test resolved run document
    # round trips and detects tampering context boundary so cleanup remains scoped.
    with pytest.raises(ValueError, match="spec_id"):
        # Keep raises, value error and pytest active only for the bounded test resolved
        # run document round trips and detects tampering operation.
        resolved_run_spec_from_bytes(
            json.dumps(tampered, separators=(",", ":"), sort_keys=True).encode()
        )


def test_resolved_run_parser_rejects_duplicate_fields_and_mutable_alias_shape() -> None:
    # Execute the test resolved run parser rejects duplicate fields and mutable alias
    # shape workflow in explicit, reviewable steps.
    spec = _spec(ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET))
    payload = resolved_run_spec_bytes(spec)
    duplicate = payload[:-1] + b',"spec_version":1}'

    with pytest.raises(ValueError, match="duplicate"):
        resolved_run_spec_from_bytes(duplicate)

    # Assemble draft once so the test resolved run parser rejects duplicate fields and
    # mutable alias shape workflow shares one value.
    draft = json.loads(payload)
    draft["strategy"] = "latest"
    with pytest.raises(ValueError, match="schema"):
        resolved_run_spec_from_bytes(json.dumps(draft).encode())


def test_parquet_repack_and_layout_change_only_physical_attempt_identity() -> None:
    # Execute the test parquet repack and layout change only physical attempt identity
    # workflow in explicit, reviewable steps.
    parquet = _spec(ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET))
    first_pack = _spec(
        ResolvedReplayInput(
            ReplayInputFormat.REPLAY_PACK,
            replay_layout_schema_id=ContentDigest("a" * 64),
            # Keep the replay pack id and b ReplayPackId step visible while building first
            # pack.
            replay_pack_id=ReplayPackId("b" * 64),
        )
    )
    repacked = _spec(
        ResolvedReplayInput(
            # Pass replay input format explicitly so ResolvedReplayInput receives a
            # reviewable c and d input in test parquet repack and layout change only
            # physical attempt identity.
            ReplayInputFormat.REPLAY_PACK,
            replay_layout_schema_id=ContentDigest("c" * 64),
            replay_pack_id=ReplayPackId("d" * 64),
        )
    )
    # Assemble nonce once so the test parquet repack and layout change only physical
    # attempt identity workflow shares one value.
    nonce = ContentDigest("e" * 64)
    physical = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1)

    assert parquet.logical_run_id == first_pack.logical_run_id == repacked.logical_run_id
    assert (
        len(
            # Open the execution attempt id and identity digest payload explicitly for len
            # within test parquet repack and layout change only physical attempt identity.
            {
                parquet.execution_attempt_id(nonce, physical.identity_digest),
                first_pack.execution_attempt_id(nonce, physical.identity_digest),
                repacked.execution_attempt_id(nonce, physical.identity_digest),
            }
            # Complete len only after its execution attempt id and identity digest inputs are
            # visible in test parquet repack and layout change only physical attempt identity.
        )
        == 3
    )


def test_physical_settings_change_attempt_but_not_logical_identity() -> None:
    # Execute the test physical settings change attempt but not logical identity workflow
    # in explicit, reviewable steps.
    spec = _spec(ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET))
    nonce = ContentDigest("e" * 64)
    first = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1)
    second = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 131_072, 4, 16_384, 2)

    assert spec.logical_run_id == spec.logical_run_id
    # Verify the execution attempt id, nonce and identity digest relationship before this
    # scenario is accepted.
    assert spec.execution_attempt_id(
        nonce,
        first.identity_digest,
    ) != spec.execution_attempt_id(nonce, second.identity_digest)


def test_physical_settings_v2_round_trip_is_exact_and_readahead_is_physical() -> None:
    # Execute the test physical settings v2 round trip is exact and readahead is physical
    # workflow in explicit, reviewable steps.
    first = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 1, 8_192, 1)
    second = RunPhysicalSettings(RunBackend.REFERENCE_PYTHON, 65_536, 2, 8_192, 1)

    assert RunPhysicalSettings.from_document(first.document()) == first
    assert first.document()["schema"] == "backtest.run-physical-settings/v2"
    assert first.identity_digest != second.identity_digest

    # Assemble missing version once so the test physical settings v2 round trip is exact
    # and readahead is physical workflow shares one value.
    missing_version = first.document()
    del missing_version["schema"]
    with pytest.raises(ValueError, match="v2 schema"):
        RunPhysicalSettings.from_document(missing_version)

    unsupported_readahead = first.document()
    # Assemble unsupported readahead and reader readahead once so the test physical
    # settings v2 round trip is exact and readahead is physical workflow shares one value.
    unsupported_readahead["reader_readahead"] = 3
    with pytest.raises(ValueError, match="1, 2 or 4"):
        RunPhysicalSettings.from_document(unsupported_readahead)


def test_model_schedule_is_a_semantic_identity_and_prediction_requirement() -> None:
    # Execute the test model schedule is a semantic identity and prediction requirement
    # workflow in explicit, reviewable steps.
    replay = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
    without_model = _spec(replay)
    schedule_id = ModelScheduleId("6" * 64)
    feature_id = FeatureSetId("8" * 64)
    embedded_policy = ExactInferencePolicy.embedded_exact_linear(
        # Pass prediction name explicitly so embedded_exact_linear receives a reviewable
        # score and reject input in test model schedule is a semantic identity and
        # prediction requirement.
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.REJECT,
        inference_delay_boundaries=1,
    )
    frozen_policy = ExactInferencePolicy.frozen_exact_linear(
        # Pass prediction name explicitly so frozen_exact_linear receives a reviewable
        # score and reject input in test model schedule is a semantic identity and
        # prediction requirement.
        prediction_name="score",
        missing_policy=InferenceMissingPolicy.REJECT,
        inference_delay_boundaries=1,
    )
    with_model = _spec(
        # Pass replay explicitly so _spec receives a reviewable replay and schedule id
        # input in test model schedule is a semantic identity and prediction requirement.
        replay,
        model_schedule_id=schedule_id,
        feature_set_ids=(feature_id,),
        inference_policy=embedded_policy,
    )
    # Assemble with prediction once so the test model schedule is a semantic identity and
    # prediction requirement workflow shares one value.
    with_prediction = _spec(
        replay,
        model_schedule_id=schedule_id,
        prediction_set_ids=(PredictionSetId("7" * 64),),
        feature_set_ids=(feature_id,),
        # Pass inference policy explicitly so _spec receives a reviewable 7 and prediction
        # set id input in test model schedule is a semantic identity and prediction
        # requirement.
        inference_policy=frozen_policy,
    )

    assert without_model.logical_run_id != with_model.logical_run_id
    assert with_prediction.document()["model_schedule_id"] == schedule_id.hex
    assert ArtifactId(schedule_id.hex) in run_input_artifact_ids(with_prediction)
    # Acquire raises, value error and pytest at an explicit test model schedule is a
    # semantic identity and prediction requirement context boundary so cleanup remains
    # scoped.
    with pytest.raises(ValueError, match="ModelSchedule"):
        # Keep raises, value error and pytest active only for the bounded test model
        # schedule is a semantic identity and prediction requirement operation.
        _spec(
            replay,
            prediction_set_ids=(PredictionSetId("7" * 64),),
            feature_set_ids=(feature_id,),
            inference_policy=frozen_policy,
            # Complete _spec only after its 7 and prediction set id inputs are visible in test
            # model schedule is a semantic identity and prediction requirement.
        )


def test_inference_policy_config_is_part_of_logical_identity() -> None:
    # Execute the test inference policy config is part of logical identity workflow in
    # explicit, reviewable steps.
    replay = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
    schedule_id = ModelScheduleId("6" * 64)
    feature_ids = (FeatureSetId("8" * 64),)

    def policy(delay: int) -> ExactInferencePolicy:
        # Execute the policy workflow in explicit, reviewable steps.
        return ExactInferencePolicy.embedded_exact_linear(
            prediction_name="score",
            missing_policy=InferenceMissingPolicy.REJECT,
            inference_delay_boundaries=delay,
        )

    # Assemble first once so the test inference policy config is part of logical identity
    # workflow shares one value.
    first = _spec(
        replay,
        model_schedule_id=schedule_id,
        feature_set_ids=feature_ids,
        inference_policy=policy(1),
        # Complete _spec only after its policy and replay inputs are visible in test inference
        # policy config is part of logical identity.
    )
    second = _spec(
        replay,
        model_schedule_id=schedule_id,
        feature_set_ids=feature_ids,
        # Keep the policy policy step visible while building second.
        inference_policy=policy(2),
    )

    assert first.logical_run_id != second.logical_run_id
    assert first.dependency_merkle_root != second.dependency_merkle_root


def test_resolved_run_v2_requires_clean_repreparation() -> None:
    # Execute the test resolved run v2 requires clean repreparation workflow in explicit,
    # reviewable steps.
    payload = json.loads(
        resolved_run_spec_bytes(_spec(ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)))
    )
    payload["spec_version"] = 2
    del payload["network_id"]
    # Discard payload['position_schema_id'] after its boundary-only use.
    del payload["position_schema_id"]

    with pytest.raises(ReprepareRequiredError) as captured:
        # Keep raises, reprepare required error and pytest active only for the bounded
        # test resolved run v2 requires clean repreparation operation.
        resolved_run_spec_from_bytes(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
    assert captured.value.code is ErrorCode.REPREPARE_REQUIRED


def test_network_identity_separates_logical_and_document_ids() -> None:
    # Execute the test network identity separates logical and document ids workflow in
    # explicit, reviewable steps.
    replay = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
    solana = _spec(replay)
    another_chain = _spec(
        replay,
        network_id=NetworkId("solana:11111111111111111111111111111112"),
        # A distinct valid genesis must separate both document and logical identities.
    )

    assert solana.spec_id != another_chain.spec_id
    assert solana.logical_run_id != another_chain.logical_run_id


def _spec(
    replay: ResolvedReplayInput,
    # Close the spec signature after its explicit inputs.
    *,
    model_schedule_id: ModelScheduleId | None = None,
    prediction_set_ids: tuple[PredictionSetId, ...] = (),
    feature_set_ids: tuple[FeatureSetId, ...] = (),
    inference_policy: ExactInferencePolicy | None = None,
    # Keep the network id input explicit in the spec contract.
    network_id: NetworkId = SOLANA_MAINNET_NETWORK_ID,
) -> ResolvedRunSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    policy = ExactInferencePolicy.disabled() if inference_policy is None else inference_policy
    roles = (
        "clock",
        "engine",
        "execution",
        # Keep the inference component named inside the roles contract.
        "inference",
        "latency",
        "protocol:reference",
        "risk",
        "scheduler",
        # Keep the strategy component named inside the roles contract.
        "strategy",
        "universe",
        "valuation:price_source",
    )
    components = tuple(
        # Keep the create and resolved component create step visible while building
        # components.
        ResolvedComponent.create(
            role=role,
            bundle_id=BundleId(f"{index:x}" * 64),
            config=(
                policy.document()
                # Pass role explicitly so create receives a reviewable x and inference
                # input in spec.
                if role == "inference"
                else {"mode": "SHADOW_STATE_REPLAY"}
                if role == "execution"
                else {"version": 1}
            ),
            # Complete create only after its x and inference inputs are visible in spec.
        )
        for index, role in enumerate(roles, start=1)
    )
    return ResolvedRunSpec.create(
        network_id=network_id,
        # Pass position schema id explicitly so create receives a reviewable 1 and 2 input
        # in spec.
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        dataset_revision_id=DatasetRevisionId("1" * 64),
        logical_content_hash=LogicalContentHash("2" * 64),
        snapshot_id=SnapshotId("3" * 64),
        replay_semantics_id=ContentDigest("4" * 64),
        # Pass replay input explicitly so create receives a reviewable 1 and 2 input in
        # spec.
        replay_input=replay,
        components=components,
        runtime_lock_id=RuntimeLockId("5" * 64),
        initial_portfolio=(AssetBalance(AssetId("SOL"), 1_000),),
        root_seed=42,
        # Pass feature set ids explicitly so create receives a reviewable 1 and 2 input in
        # spec.
        feature_set_ids=feature_set_ids,
        model_schedule_id=model_schedule_id,
        prediction_set_ids=prediction_set_ids,
    )
