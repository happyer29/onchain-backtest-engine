"""Execution-only composition of verified point-in-time mmap overlays."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType

# Import typing at the visible module dependency boundary.
from typing import cast

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource
from backtest.adapters.ml.numpy.embedded import (
    NumpyEmbeddedExactPredictionProvider,
    # Include validate embedded exact inputs so the embedded dependency remains explicit.
    validate_embedded_exact_inputs,
)
from backtest.adapters.ml.numpy.reader import (
    NumpyFeatureSetProvider,
    NumpyModelBundleReader,
    # Include numpy model schedule reader so the reader dependency remains explicit.
    NumpyModelScheduleReader,
    NumpyPredictionSetProvider,
)
from backtest.adapters.ml.numpy.toolchain import unit_ml_build_tools
from backtest.application.code_bundles import PinnedCodeBundleSet

# Import ml contracts at the visible module dependency boundary.
from backtest.application.ml_contracts import (
    EXACT_PREDICTION_AVAILABILITY_POLICY,
    InferenceMode,
    ModelCanonicality,
)

# Import runs at the visible module dependency boundary.
from backtest.application.ports.runs import ResolvedCausalOverlays
from backtest.application.run_specs import ReplayInputFormat, ResolvedRunSpec
from backtest.domain.identifiers import ModelBundleId
from backtest.engine.causal_data import CausalScalarProvider


class CausalOverlayResolutionError(RuntimeError):
    """Exact resolved overlay inputs are missing, incompatible or ambiguous."""


class _NamedCompositeProvider:
    def __init__(self, providers: dict[str, CausalScalarProvider]) -> None:
        # Execute the named composite provider init workflow in explicit, reviewable
        # steps.
        if not providers:
            raise ValueError("a composite causal provider cannot be empty")
        self._providers = providers.copy()

    def value_at(
        self,
        # Keep the name input explicit in the value at contract.
        name: str,
        entity_id: int,
        boundary_ordinal: int,
    ) -> int | None:
        # Execute the named composite provider value at workflow in explicit, reviewable
        # steps.
        provider = self._providers.get(name)
        if provider is None:
            return None
        return provider.value_at(name, entity_id, boundary_ordinal)


# Keep the local overlay session contract and validation rules together.
class _LocalOverlaySession:
    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        spec: ResolvedRunSpec,
        # Close the init signature after its explicit inputs.
        *,
        embedded_temporary_parent: Path,
        embedded_maximum_temporary_bytes: int,
        embedded_batch_rows: int,
        build_tools: PinnedCodeBundleSet,
        # Close the init signature after its explicit inputs.
    ) -> None:
        # Execute the local overlay session init workflow in explicit, reviewable steps.
        self._artifacts = artifacts
        self._spec = spec
        self._embedded_temporary_parent = embedded_temporary_parent
        self._embedded_maximum_temporary_bytes = embedded_maximum_temporary_bytes
        self._embedded_batch_rows = embedded_batch_rows
        # Assemble self build tools once so the local overlay session init workflow shares
        # one value.
        self._build_tools = build_tools
        self._stack: ExitStack | None = None

    def __enter__(self) -> ResolvedCausalOverlays:
        # Execute the local overlay session enter workflow in explicit, reviewable steps.
        result = self._enter(materialize_embedded=True)
        if result is None:  # pragma: no cover - materialization returns a provider
            raise AssertionError("embedded overlay materialization returned no provider")
        return result

    def verify(self) -> None:
        # Execute the local overlay session verify workflow in explicit, reviewable steps.
        try:
            self._enter(materialize_embedded=False)
        finally:
            self.close()

    def _enter(self, *, materialize_embedded: bool) -> ResolvedCausalOverlays | None:
        # Execute the local overlay session enter workflow in explicit, reviewable steps.
        if self._stack is not None:
            raise RuntimeError("causal overlay session was already entered")
        replay_pack_id = self._spec.replay_input.replay_pack_id
        replay_layout_id = self._spec.replay_input.replay_layout_schema_id
        if (
            # Keep self visible while evaluating the format, replay pack and replay pack
            # id guard.
            self._spec.replay_input.format is not ReplayInputFormat.REPLAY_PACK
            or replay_pack_id is None
            or replay_layout_id is None
        ):
            raise CausalOverlayResolutionError("point-in-time overlays require an exact ReplayPack")
        # Assemble stack once so the local overlay session enter workflow shares one
        # value.
        stack = ExitStack()
        self._stack = stack
        try:
            # Perform the protected local overlay session enter operation before explicit
            # failure handling.
            replay = stack.enter_context(
                NumpyMmapReplaySource(
                    self._artifacts,
                    replay_pack_id,
                    build_tools=self._build_tools,
                    # Complete NumpyMmapReplaySource only after its artifacts and build tools
                    # inputs are visible in local overlay session enter.
                )
            )
            if (
                replay.snapshot_id != self._spec.snapshot_id
                or replay.replay_semantics_id != self._spec.replay_semantics_id
                # Keep replay visible while evaluating the snapshot id, replay semantics
                # id and replay layout schema id guard.
                or replay.replay_layout_schema_id != replay_layout_id
            ):
                # Handle the local overlay session enter snapshot id, replay semantics id
                # and replay layout schema id condition as a distinct block.
                raise CausalOverlayResolutionError(
                    "resolved ReplayPack differs from the causal overlay contract"
                )

            feature_readers = tuple(
                stack.enter_context(
                    # Keep the artifacts NumpyFeatureSetProvider step visible while
                    # building feature readers.
                    NumpyFeatureSetProvider(
                        self._artifacts,
                        artifact_id,
                        build_tools=self._build_tools,
                    )
                    # Complete enter_context only after its artifacts and build tools inputs
                    # are visible in local overlay session enter.
                )
                for artifact_id in self._spec.feature_set_ids
            )
            feature_names: dict[str, CausalScalarProvider] = {}
            for feature_reader in feature_readers:
                # Process feature_readers inside the bounded local overlay session enter
                # loop.
                semantic = _semantic(feature_reader.manifest.semantic_content)
                if (
                    feature_reader.replay_pack_id != replay_pack_id
                    or feature_reader.snapshot_id != self._spec.snapshot_id
                    or semantic.get("replay_semantics_id") != self._spec.replay_semantics_id.hex
                    # Keep semantic visible while evaluating the replay pack id, snapshot
                    # id and hex guard.
                    or semantic.get("replay_layout_schema_id") != replay_layout_id.hex
                    or feature_reader.manifest.build.runtime_lock_id != self._spec.runtime_lock_id
                ):
                    # Handle the local overlay session enter replay pack id, snapshot id
                    # and hex condition as a distinct block.
                    raise CausalOverlayResolutionError(
                        "FeatureSet differs from the resolved replay/runtime contract"
                    )
                for feature in feature_reader.feature_specs:
                    # Process feature_reader.feature_specs inside the bounded local
                    # overlay session enter loop.
                    if feature.name in feature_names:
                        # Handle the local overlay session enter feature.name in
                        # feature_names branch as a distinct logical block.
                        raise CausalOverlayResolutionError(
                            "resolved FeatureSets expose an ambiguous feature name"
                        )
                    feature_names[feature.name] = feature_reader

            policy = self._spec.inference_policy()
            # Assemble prediction names once so the local overlay session enter workflow
            # shares one value.
            prediction_names: dict[str, CausalScalarProvider] = {}
            embedded_model_ids: tuple[ModelBundleId, ...] = ()
            exact = True
            if policy.mode is InferenceMode.FROZEN:
                # Handle the local overlay session enter policy.mode is
                # InferenceMode.FROZEN branch as a distinct logical block.
                if len(self._spec.prediction_set_ids) != 1:
                    # Handle the local overlay session enter prediction set ids and spec
                    # condition as a distinct block.
                    raise CausalOverlayResolutionError(
                        "reference exact frozen inference requires one PredictionSet"
                    )
                schedule_id = self._spec.model_schedule_id
                if schedule_id is None:  # pragma: no cover - ResolvedRunSpec validates this
                    raise CausalOverlayResolutionError(
                        "frozen inference has no exact ModelSchedule"
                    )
                schedule = stack.enter_context(
                    NumpyModelScheduleReader(
                        # Pass self explicitly so NumpyModelScheduleReader receives a
                        # reviewable artifacts and build tools input in local overlay
                        # session enter.
                        self._artifacts,
                        schedule_id,
                        build_tools=self._build_tools,
                    )
                )
                # Assemble models once so the local overlay session enter workflow shares
                # one value.
                models = tuple(
                    stack.enter_context(
                        NumpyModelBundleReader(
                            self._artifacts,
                            model_id,
                            # Pass build tools explicitly so NumpyModelBundleReader
                            # receives a reviewable artifacts and build tools input in
                            # local overlay session enter.
                            build_tools=self._build_tools,
                        )
                    )
                    for model_id in schedule.model_bundle_ids
                )
                # Invoke validate_embedded_exact_inputs for feature readers and schedule
                # as a visible local overlay session enter step.
                validate_embedded_exact_inputs(feature_readers, schedule, models)
                _require_exact_inference_runtime(self._spec, schedule, models)
                prediction_reader = stack.enter_context(
                    NumpyPredictionSetProvider(
                        self._artifacts,
                        # Pass self explicitly so NumpyPredictionSetProvider receives a
                        # reviewable artifacts and prediction set ids input in local
                        # overlay session enter.
                        self._spec.prediction_set_ids[0],
                        build_tools=self._build_tools,
                    )
                )
                semantic = _semantic(prediction_reader.manifest.semantic_content)
                # Evaluate the complete local overlay session enter hex, runtime lock id
                # and model schedule id condition before guarded effects.
                if (
                    semantic.get("replay_pack_id") != replay_pack_id.hex
                    or semantic.get("replay_semantics_id") != self._spec.replay_semantics_id.hex
                    or semantic.get("replay_layout_schema_id") != replay_layout_id.hex
                    or prediction_reader.manifest.build.runtime_lock_id
                    # Keep self visible while evaluating the hex, runtime lock id and
                    # model schedule id guard.
                    != self._spec.runtime_lock_id
                    or prediction_reader.model_schedule_id != self._spec.model_schedule_id
                    or prediction_reader.prediction_name != policy.prediction_name
                    or prediction_reader.inference_policy_digest != policy.inference_policy_digest
                    or prediction_reader.causal_availability_policy
                    # Keep exact prediction availability policy visible while evaluating
                    # the hex, runtime lock id and model schedule id guard.
                    != EXACT_PREDICTION_AVAILABILITY_POLICY
                ):
                    # Handle the local overlay session enter hex, runtime lock id and
                    # model schedule id condition as a distinct block.
                    raise CausalOverlayResolutionError(
                        "PredictionSet differs from the resolved exact inference policy"
                    )
                prediction_names[prediction_reader.prediction_name] = prediction_reader
                exact = prediction_reader.canonicality is ModelCanonicality.CANONICAL_EXACT
            # Handle the local overlay session enter complement of policy.mode is
            # InferenceMode.FROZEN explicitly.
            elif policy.mode is InferenceMode.EMBEDDED_BATCH:
                # Handle the local overlay session enter mode, embedded batch and policy
                # condition as a distinct block.
                schedule_id = self._spec.model_schedule_id
                if schedule_id is None:  # pragma: no cover - ResolvedRunSpec validates this
                    raise CausalOverlayResolutionError(
                        "embedded inference has no exact ModelSchedule"
                    )
                schedule = stack.enter_context(
                    NumpyModelScheduleReader(
                        # Pass self explicitly so NumpyModelScheduleReader receives a
                        # reviewable artifacts and build tools input in local overlay
                        # session enter.
                        self._artifacts,
                        schedule_id,
                        build_tools=self._build_tools,
                    )
                )
                # Assemble models once so the local overlay session enter workflow shares
                # one value.
                models = tuple(
                    stack.enter_context(
                        NumpyModelBundleReader(
                            self._artifacts,
                            model_id,
                            # Pass build tools explicitly so NumpyModelBundleReader
                            # receives a reviewable artifacts and build tools input in
                            # local overlay session enter.
                            build_tools=self._build_tools,
                        )
                    )
                    for model_id in schedule.model_bundle_ids
                )
                # Invoke validate_embedded_exact_inputs for feature readers and schedule
                # as a visible local overlay session enter step.
                validate_embedded_exact_inputs(feature_readers, schedule, models)
                _require_exact_inference_runtime(self._spec, schedule, models)
                embedded_model_ids = schedule.model_bundle_ids
                exact = schedule.canonicality is ModelCanonicality.CANONICAL_EXACT
                if not materialize_embedded:
                    # Return explicit absence from the local overlay session enter path.
                    return None
                embedded = stack.enter_context(
                    NumpyEmbeddedExactPredictionProvider(
                        replay=replay,
                        features=feature_readers,
                        # Pass schedule explicitly so NumpyEmbeddedExactPredictionProvider
                        # receives a reviewable embedded temporary parent and embedded
                        # maximum temporary bytes input in local overlay session enter.
                        schedule=schedule,
                        models=models,
                        policy=policy,
                        temporary_parent=self._embedded_temporary_parent,
                        maximum_temporary_bytes=self._embedded_maximum_temporary_bytes,
                        # Pass batch rows explicitly so
                        # NumpyEmbeddedExactPredictionProvider receives a reviewable
                        # embedded temporary parent and embedded maximum temporary bytes
                        # input in local overlay session enter.
                        batch_rows=self._embedded_batch_rows,
                        build_tools=self._build_tools,
                    )
                )
                if embedded.inference_policy_digest != policy.inference_policy_digest:
                    # Handle the local overlay session enter inference policy digest,
                    # embedded and policy condition as a distinct block.
                    raise CausalOverlayResolutionError(
                        "embedded provider differs from the resolved inference policy"
                    )
                prediction_names[embedded.prediction_name] = embedded
            # Handle the local overlay session enter complement of mode, embedded batch
            # and policy explicitly.
            elif policy.mode is not InferenceMode.DISABLED:
                raise CausalOverlayResolutionError("resolved inference mode is unsupported")

            return ResolvedCausalOverlays(
                feature_set_ids=self._spec.feature_set_ids,
                model_schedule_id=self._spec.model_schedule_id,
                # Pass prediction set ids explicitly so ResolvedCausalOverlays receives a
                # reviewable feature set ids and spec input in local overlay session
                # enter.
                prediction_set_ids=self._spec.prediction_set_ids,
                embedded_model_bundle_ids=embedded_model_ids,
                inference_mode=policy.mode,
                inference_policy_digest=policy.inference_policy_digest,
                snapshot_id=replay.snapshot_id,
                # Pass replay pack id explicitly so ResolvedCausalOverlays receives a
                # reviewable feature set ids and spec input in local overlay session
                # enter.
                replay_pack_id=replay_pack_id,
                replay_semantics_id=replay.replay_semantics_id,
                replay_layout_schema_id=replay.replay_layout_schema_id,
                runtime_lock_id=self._spec.runtime_lock_id,
                canonical_exact=exact,
                # Include features in the completed local overlay session enter result.
                features=(None if not feature_names else _NamedCompositeProvider(feature_names)),
                predictions=(
                    None if not prediction_names else _NamedCompositeProvider(prediction_names)
                ),
            )
        # Translate base exception through the local overlay session enter boundary
        # without hiding other errors.
        except BaseException:
            # Translate the BaseException failure through the local overlay session enter
            # boundary.
            self.close()
            raise

    def close(self) -> None:
        # Execute the local overlay session close workflow in explicit, reviewable steps.
        stack = self._stack
        self._stack = None
        if stack is not None:
            stack.close()

    def __exit__(
        # Keep the remaining exit inputs visible at the local overlay session exit
        # boundary.
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Invoke close as a visible step within the local overlay session exit workflow.
        self.close()


class LocalNumpyCausalOverlayFactory:
    """Open only the exact immutable overlay IDs pinned by a ResolvedRunSpec."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        *,
        embedded_temporary_parent: Path | None = None,
        # Keep the embedded maximum temporary bytes input explicit in the init contract.
        embedded_maximum_temporary_bytes: int = 1024**3,
        embedded_batch_rows: int = 65_536,
        build_tools: PinnedCodeBundleSet | None = None,
    ) -> None:
        # Execute the local numpy causal overlay factory init workflow in explicit,
        # reviewable steps.
        if embedded_maximum_temporary_bytes <= 0 or embedded_batch_rows <= 0:
            raise ValueError("embedded inference quota and batch size must be positive")
        self._artifacts = artifacts
        self._embedded_temporary_parent = (
            artifacts.data_root / "tmp" / "embedded-inference"
            # Keep the embedded temporary parent component named inside the self embedded
            # temporary parent contract.
            if embedded_temporary_parent is None
            else embedded_temporary_parent
        )
        self._embedded_maximum_temporary_bytes = embedded_maximum_temporary_bytes
        self._embedded_batch_rows = embedded_batch_rows
        # Assemble self build tools once so the local numpy causal overlay factory init
        # workflow shares one value.
        self._build_tools = build_tools or unit_ml_build_tools()

    def open_resolved(self, spec: ResolvedRunSpec) -> _LocalOverlaySession:
        # Execute the local numpy causal overlay factory open resolved workflow in
        # explicit, reviewable steps.
        if not spec.feature_set_ids and spec.inference_policy().mode is InferenceMode.DISABLED:
            raise CausalOverlayResolutionError("resolved run declares no causal overlays")
        return self._session(spec)

    def verify_resolved(self, spec: ResolvedRunSpec) -> None:
        """Verify manifests and compatibility without running embedded inference."""

        self._session(spec).verify()

    def _session(self, spec: ResolvedRunSpec) -> _LocalOverlaySession:
        # Execute the local numpy causal overlay factory session workflow in explicit,
        # reviewable steps.
        return _LocalOverlaySession(
            self._artifacts,
            spec,
            embedded_temporary_parent=self._embedded_temporary_parent,
            embedded_maximum_temporary_bytes=self._embedded_maximum_temporary_bytes,
            # Pass embedded batch rows explicitly so _LocalOverlaySession receives a
            # reviewable artifacts and embedded temporary parent input in local numpy
            # causal overlay factory session.
            embedded_batch_rows=self._embedded_batch_rows,
            build_tools=self._build_tools,
        )


def _semantic(payload: bytes) -> dict[str, object]:
    # Execute the semantic workflow in explicit, reviewable steps.
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as error:
        raise CausalOverlayResolutionError("ML semantic content is invalid") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        # Fail the semantic path with CausalOverlayResolutionError for ml semantic content
        # must be an object when isinstance, value and key is true; do not continue
        # ambiguously.
        raise CausalOverlayResolutionError("ML semantic content must be an object")
    return cast(dict[str, object], value)


def _require_exact_inference_runtime(
    spec: ResolvedRunSpec,
    schedule: NumpyModelScheduleReader,
    # Keep the models input explicit in the require exact inference runtime contract.
    models: tuple[NumpyModelBundleReader, ...],
) -> None:
    # Execute the require exact inference runtime workflow in explicit, reviewable steps.
    if schedule.manifest.build.runtime_lock_id != spec.runtime_lock_id or any(
        model.manifest.build.runtime_lock_id != spec.runtime_lock_id for model in models
    ):
        # Handle the require exact inference runtime runtime lock id, build and spec
        # condition as a distinct block.
        raise CausalOverlayResolutionError(
            "exact inference artifacts differ from the resolved runtime lock"
        )


__all__ = ["CausalOverlayResolutionError", "LocalNumpyCausalOverlayFactory"]
