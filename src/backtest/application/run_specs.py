"""Immutable resolved-run identities and preflight-safe serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self, cast

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.errors import ReprepareRequiredError
from backtest.application.ml_contracts import ExactInferencePolicy, InferenceMode
from backtest.domain.execution import ExecutionMode
from backtest.domain.hashing import canonical_json_bytes, domain_digest

# Import identifiers at the visible module dependency boundary.
from backtest.domain.identifiers import (
    AssetId,
    BundleId,
    ContentDigest,
    DatasetRevisionId,
    # Include delivery schedule id so the identifiers dependency remains explicit.
    DeliveryScheduleId,
    ExecutionAttemptId,
    FeatureSetId,
    LogicalContentHash,
    LogicalRunId,
    # Include model schedule id so the identifiers dependency remains explicit.
    ModelScheduleId,
    NetworkId,
    PositionSchemaId,
    PredictionSetId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
)


# Keep the replay input format contract and validation rules together.
class ReplayInputFormat(StrEnum):
    CANONICAL_PARQUET = "canonical_parquet"
    REPLAY_PACK = "replay_pack"


# Keep the replay contract contract and validation rules together.
class ReplayContract(StrEnum):
    CANONICAL_EXACT = "CANONICAL_EXACT"
    NON_CANONICAL_TOLERANCE = "NON_CANONICAL_TOLERANCE"


# Keep the asset balance contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class AssetBalance:
    asset_id: AssetId
    amount_atomic: int

    def __post_init__(self) -> None:
        # Execute the asset balance post init workflow in explicit, reviewable steps.
        if isinstance(self.amount_atomic, bool) or not isinstance(self.amount_atomic, int):
            raise TypeError("initial balance must be an integer")
        if self.amount_atomic < 0:
            raise ValueError("initial balance must be non-negative")


# Keep the resolved component contract and validation rules together.
@dataclass(frozen=True, slots=True, order=True)
class ResolvedComponent:
    role: str
    bundle_id: BundleId
    config_digest: ContentDigest
    # Declare api version explicitly in the resolved component contract.
    api_version: int
    canonical_config: bytes

    def __post_init__(self) -> None:
        # Execute the resolved component post init workflow in explicit, reviewable steps.
        if not self.role or self.role != self.role.strip() or "\x00" in self.role:
            raise ValueError("component role must be non-empty, trimmed and NUL-free")
        if self.api_version <= 0:
            raise ValueError("component api_version must be positive")
        try:
            # Assemble canonical once so the resolved component post init workflow shares
            # one value.
            canonical = canonicalize_job_payload(self.canonical_config)
        except (TypeError, ValueError) as error:
            raise ValueError("component config must be canonical, secret-free JSON") from error
        if canonical != self.canonical_config:
            raise ValueError("component config is not canonical JSON")
        # Assemble expected once so the resolved component post init workflow shares one
        # value.
        expected = domain_digest(
            "backtest.component-config.v1",
            json.loads(canonical),
        )
        if expected.hex != self.config_digest.hex:
            # Fail the resolved component post init path with ValueError for component
            # config digest does not match its canonical config when hex, expected and
            # config digest is true; do not continue ambiguously.
            raise ValueError("component config_digest does not match its canonical config")

    @classmethod
    def create(
        cls,
        *,
        # Keep the role input explicit in the create contract.
        role: str,
        bundle_id: BundleId,
        config: dict[str, object],
        api_version: int = 1,
    ) -> Self:
        # Execute the resolved component create workflow in explicit, reviewable steps.
        canonical = canonicalize_job_payload(canonical_json_bytes(config))
        digest = domain_digest("backtest.component-config.v1", json.loads(canonical))
        return cls(role, bundle_id, digest, api_version, canonical)

    def identity_document(self) -> dict[str, object]:
        # Execute the resolved component identity document workflow in explicit,
        # reviewable steps.
        return {
            "api_version": self.api_version,
            "bundle_id": self.bundle_id.hex,
            "config": cast(dict[str, object], json.loads(self.canonical_config)),
            "config_digest": self.config_digest.hex,
            # Include role in the completed resolved component identity document result.
            "role": self.role,
        }


# Keep the resolved replay input contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedReplayInput:
    format: ReplayInputFormat
    replay_layout_schema_id: ContentDigest | None = None
    replay_pack_id: ReplayPackId | None = None

    # Define resolved replay input post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the resolved replay input post init workflow in explicit, reviewable
        # steps.
        has_pack = self.replay_pack_id is not None or self.replay_layout_schema_id is not None
        if self.format is ReplayInputFormat.REPLAY_PACK and not (
            self.replay_pack_id is not None and self.replay_layout_schema_id is not None
        ):
            raise ValueError("ReplayPack input requires pack and layout IDs")
        # Evaluate the complete resolved replay input post init has pack, format and
        # canonical parquet condition before guarded effects.
        if self.format is ReplayInputFormat.CANONICAL_PARQUET and has_pack:
            raise ValueError("canonical Parquet input cannot carry ReplayPack IDs")

    def document(self) -> dict[str, object]:
        # Execute the resolved replay input document workflow in explicit, reviewable
        # steps.
        return {
            "format": self.format.value,
            "replay_layout_schema_id": (
                None if self.replay_layout_schema_id is None else self.replay_layout_schema_id.hex
            ),
            # Include replay pack id in the completed resolved replay input document
            # result.
            "replay_pack_id": None if self.replay_pack_id is None else self.replay_pack_id.hex,
        }


_REQUIRED_EXACT_ROLES = frozenset(
    {
        "clock",
        # Pass engine explicitly so frozenset receives a reviewable clock and engine input
        # in module.
        "engine",
        "execution",
        "inference",
        "latency",
        "risk",
        # Pass scheduler explicitly so frozenset receives a reviewable clock and engine
        # input in module.
        "scheduler",
        "strategy",
        "universe",
        "valuation:price_source",
    }
    # Complete frozenset only after its clock and engine inputs are visible in module.
)


# Keep the resolved run spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedRunSpec:
    spec_version: int
    spec_id: ContentDigest
    network_id: NetworkId
    # Declare position schema id explicitly in the resolved run spec contract.
    position_schema_id: PositionSchemaId
    dataset_revision_id: DatasetRevisionId
    logical_content_hash: LogicalContentHash
    snapshot_id: SnapshotId
    replay_semantics_id: ContentDigest
    # Declare replay input explicitly in the resolved run spec contract.
    replay_input: ResolvedReplayInput
    components: tuple[ResolvedComponent, ...]
    dependency_merkle_root: ContentDigest
    feature_set_ids: tuple[FeatureSetId, ...]
    model_schedule_id: ModelScheduleId | None
    # Declare prediction set ids explicitly in the resolved run spec contract.
    prediction_set_ids: tuple[PredictionSetId, ...]
    delivery_schedule_id: DeliveryScheduleId | None
    runtime_lock_id: RuntimeLockId
    initial_portfolio: tuple[AssetBalance, ...]
    root_seed: int
    # Declare replay contract explicitly in the resolved run spec contract.
    replay_contract: ReplayContract

    def __post_init__(self) -> None:
        # Execute the resolved run spec post init workflow in explicit, reviewable steps.
        if self.spec_version != 3:
            raise ValueError("only resolved run spec version 3 is supported")
        if not isinstance(self.network_id, NetworkId):
            raise TypeError("resolved run network_id must be a NetworkId")
        if not isinstance(self.position_schema_id, PositionSchemaId):
            # Fail the resolved run spec post init path with TypeError for resolved run
            # position schema id must be a position schema id when isinstance and position
            # schema id is true; do not continue ambiguously.
            raise TypeError("resolved run position_schema_id must be a PositionSchemaId")
        components = tuple(sorted(self.components, key=lambda item: item.role))
        if components != self.components:
            raise ValueError("resolved components must be sorted by role")
        roles = tuple(component.role for component in components)
        # Guard this path with len(set(roles)) != len(roles) before applying effects.
        if len(set(roles)) != len(roles):
            raise ValueError("resolved component roles must be unique")
        missing = _REQUIRED_EXACT_ROLES.difference(roles)
        if missing:
            raise ValueError(f"resolved run is missing component roles: {sorted(missing)}")
        # Evaluate the complete resolved run spec post init startswith, protocol: and role
        # condition before guarded effects.
        if not any(role.startswith("protocol:") for role in roles):
            raise ValueError("resolved run requires at least one exact protocol component")
        expected_merkle = dependency_merkle_root(components)
        if expected_merkle.hex != self.dependency_merkle_root.hex:
            raise ValueError("dependency Merkle root does not match resolved components")

        # Assemble features once so the resolved run spec post init workflow shares one
        # value.
        features = tuple(sorted(self.feature_set_ids, key=lambda item: item.hex))
        predictions = tuple(sorted(self.prediction_set_ids, key=lambda item: item.hex))
        balances = tuple(sorted(self.initial_portfolio, key=lambda item: item.asset_id.value))
        if features != self.feature_set_ids or len(set(features)) != len(features):
            raise ValueError("feature IDs must be sorted and unique")
        # Evaluate the complete resolved run spec post init predictions and prediction set
        # ids condition before guarded effects.
        if predictions != self.prediction_set_ids or len(set(predictions)) != len(predictions):
            raise ValueError("prediction IDs must be sorted and unique")
        inference = self.inference_policy()
        if inference.mode is InferenceMode.DISABLED:
            # Handle the resolved run spec post init mode, disabled and inference
            # condition as a distinct block.
            if self.model_schedule_id is not None or predictions:
                raise ValueError("disabled inference cannot declare models or predictions")
        # Handle the resolved run spec post init complement of mode, disabled and
        # inference explicitly.
        elif inference.mode is InferenceMode.FROZEN:
            # Handle the resolved run spec post init inference.mode is
            # InferenceMode.FROZEN branch as a distinct logical block.
            if self.model_schedule_id is None or not features or not predictions:
                # Handle the resolved run spec post init model schedule id, features and
                # predictions condition as a distinct block.
                raise ValueError(
                    "frozen inference requires features, a ModelSchedule and PredictionSets"
                )
        # Handle the resolved run spec post init complement of inference.mode is
        # InferenceMode.FROZEN explicitly.
        elif inference.mode is InferenceMode.EMBEDDED_BATCH:
            # Handle the resolved run spec post init mode, embedded batch and inference
            # condition as a distinct block.
            if self.model_schedule_id is None or not features:
                raise ValueError("embedded inference requires features and a ModelSchedule")
            if predictions:
                raise ValueError("embedded inference cannot declare frozen PredictionSets")
        else:  # pragma: no cover - ExactInferencePolicy rejects unsupported modes
            raise ValueError("unsupported resolved inference mode")
        if balances != self.initial_portfolio:
            raise ValueError("initial portfolio must be sorted by asset ID")
        if len({item.asset_id for item in balances}) != len(balances):
            raise ValueError("initial portfolio contains duplicate assets")
        # Evaluate the complete resolved run spec post init isinstance and root seed
        # condition before guarded effects.
        if (
            isinstance(self.root_seed, bool)
            or not isinstance(self.root_seed, int)
            or not 0 <= self.root_seed < 1 << 256
        ):
            # Fail the resolved run spec post init path with ValueError for root seed must
            # be an unsigned 256-bit integer when isinstance and root seed is true; do not
            # continue ambiguously.
            raise ValueError("root_seed must be an unsigned 256-bit integer")
        expected_spec = domain_digest("backtest.resolved-run-spec.v3", self.document(False))
        if expected_spec.hex != self.spec_id.hex:
            raise ValueError("run spec ID does not match the resolved document")

    @classmethod
    # Define resolved run spec create as one focused operation with an explicit boundary.
    def create(
        cls,
        *,
        network_id: NetworkId,
        position_schema_id: PositionSchemaId,
        # Keep the dataset revision id input explicit in the create contract.
        dataset_revision_id: DatasetRevisionId,
        logical_content_hash: LogicalContentHash,
        snapshot_id: SnapshotId,
        replay_semantics_id: ContentDigest,
        replay_input: ResolvedReplayInput,
        # Keep the components input explicit in the create contract.
        components: tuple[ResolvedComponent, ...],
        runtime_lock_id: RuntimeLockId,
        initial_portfolio: tuple[AssetBalance, ...],
        root_seed: int,
        replay_contract: ReplayContract = ReplayContract.CANONICAL_EXACT,
        # Keep the feature set ids input explicit in the create contract.
        feature_set_ids: tuple[FeatureSetId, ...] = (),
        model_schedule_id: ModelScheduleId | None = None,
        prediction_set_ids: tuple[PredictionSetId, ...] = (),
        delivery_schedule_id: DeliveryScheduleId | None = None,
        spec_version: int = 3,
        # Keep the remaining create inputs visible at the resolved run spec create boundary.
    ) -> Self:
        # Execute the resolved run spec create workflow in explicit, reviewable steps.
        ordered_components = tuple(sorted(components, key=lambda item: item.role))
        merkle = dependency_merkle_root(ordered_components)
        provisional = cls.__new__(cls)
        object.__setattr__(provisional, "spec_version", spec_version)
        object.__setattr__(provisional, "spec_id", ContentDigest("0" * 64))
        # Invoke __setattr__ for network id and provisional as a visible resolved run spec
        # create step.
        object.__setattr__(provisional, "network_id", network_id)
        object.__setattr__(provisional, "position_schema_id", position_schema_id)
        object.__setattr__(provisional, "dataset_revision_id", dataset_revision_id)
        object.__setattr__(provisional, "logical_content_hash", logical_content_hash)
        object.__setattr__(provisional, "snapshot_id", snapshot_id)
        # Invoke __setattr__ for replay semantics id and provisional as a visible resolved
        # run spec create step.
        object.__setattr__(provisional, "replay_semantics_id", replay_semantics_id)
        object.__setattr__(provisional, "replay_input", replay_input)
        object.__setattr__(provisional, "components", ordered_components)
        object.__setattr__(provisional, "dependency_merkle_root", merkle)
        object.__setattr__(
            # Pass provisional explicitly so __setattr__ receives a reviewable feature set
            # ids and hex input in resolved run spec create.
            provisional,
            "feature_set_ids",
            tuple(sorted(feature_set_ids, key=lambda item: item.hex)),
        )
        object.__setattr__(provisional, "model_schedule_id", model_schedule_id)
        # Invoke __setattr__ for prediction set ids and hex as a visible resolved run spec
        # create step.
        object.__setattr__(
            provisional,
            "prediction_set_ids",
            tuple(sorted(prediction_set_ids, key=lambda item: item.hex)),
        )
        # Invoke __setattr__ for delivery schedule id and provisional as a visible
        # resolved run spec create step.
        object.__setattr__(provisional, "delivery_schedule_id", delivery_schedule_id)
        object.__setattr__(provisional, "runtime_lock_id", runtime_lock_id)
        object.__setattr__(
            provisional,
            "initial_portfolio",
            # Pass key explicitly to __setattr__ for initial portfolio and value.
            tuple(sorted(initial_portfolio, key=lambda item: item.asset_id.value)),
        )
        object.__setattr__(provisional, "root_seed", root_seed)
        object.__setattr__(provisional, "replay_contract", replay_contract)
        spec_id = domain_digest("backtest.resolved-run-spec.v3", provisional.document(False))
        # Return the completed resolved run spec create result without a hidden fallback.
        return cls(
            spec_version=spec_version,
            spec_id=spec_id,
            network_id=network_id,
            position_schema_id=position_schema_id,
            # Pass dataset revision id explicitly so cls receives a reviewable hex and
            # value input in resolved run spec create.
            dataset_revision_id=dataset_revision_id,
            logical_content_hash=logical_content_hash,
            snapshot_id=snapshot_id,
            replay_semantics_id=replay_semantics_id,
            replay_input=replay_input,
            # Pass components explicitly so cls receives a reviewable hex and value input
            # in resolved run spec create.
            components=ordered_components,
            dependency_merkle_root=merkle,
            feature_set_ids=tuple(sorted(feature_set_ids, key=lambda item: item.hex)),
            model_schedule_id=model_schedule_id,
            prediction_set_ids=tuple(sorted(prediction_set_ids, key=lambda item: item.hex)),
            # Pass delivery schedule id explicitly so cls receives a reviewable hex and
            # value input in resolved run spec create.
            delivery_schedule_id=delivery_schedule_id,
            runtime_lock_id=runtime_lock_id,
            initial_portfolio=tuple(
                sorted(initial_portfolio, key=lambda item: item.asset_id.value)
            ),
            # Pass root seed explicitly so cls receives a reviewable hex and value input
            # in resolved run spec create.
            root_seed=root_seed,
            replay_contract=replay_contract,
        )

    def document(self, include_spec_id: bool = True) -> dict[str, object]:
        # Execute the resolved run spec document workflow in explicit, reviewable steps.
        value: dict[str, object] = {
            "components": [item.identity_document() for item in self.components],
            "dataset_revision_id": self.dataset_revision_id.hex,
            "delivery_schedule_id": (
                None if self.delivery_schedule_id is None else self.delivery_schedule_id.hex
                # Complete the value group only after its semantic components are visible.
            ),
            "dependency_merkle_root": self.dependency_merkle_root.hex,
            "feature_set_ids": [item.hex for item in self.feature_set_ids],
            "initial_portfolio": [
                {"amount_atomic": item.amount_atomic, "asset_id": item.asset_id.value}
                # Keep the item component named inside the value contract.
                for item in self.initial_portfolio
            ],
            "logical_content_hash": self.logical_content_hash.hex,
            "model_schedule_id": (
                None if self.model_schedule_id is None else self.model_schedule_id.hex
                # Complete the value group only after its semantic components are visible.
            ),
            "network_id": self.network_id.value,
            "position_schema_id": self.position_schema_id.value,
            "prediction_set_ids": [item.hex for item in self.prediction_set_ids],
            "replay_contract": self.replay_contract.value,
            # Register document and replay input through document so the value table
            # remains scannable.
            "replay_input": self.replay_input.document(),
            "replay_semantics_id": self.replay_semantics_id.hex,
            "root_seed": self.root_seed,
            "runtime_lock_id": self.runtime_lock_id.hex,
            "snapshot_id": self.snapshot_id.hex,
            # Keep the spec version component named inside the value contract.
            "spec_version": self.spec_version,
        }
        if include_spec_id:
            value["spec_id"] = self.spec_id.hex
        return value

    # Define resolved run spec semantic document as one focused operation with an explicit
    # boundary.
    def semantic_document(self) -> dict[str, object]:
        # Execute the resolved run spec semantic document workflow in explicit, reviewable
        # steps.
        return {
            "components": [item.identity_document() for item in self.components],
            "dataset_revision_id": self.dataset_revision_id.hex,
            "dependency_merkle_root": self.dependency_merkle_root.hex,
            "feature_set_ids": [item.hex for item in self.feature_set_ids],
            # Include initial portfolio in the completed resolved run spec semantic
            # document result.
            "initial_portfolio": [
                {"amount_atomic": item.amount_atomic, "asset_id": item.asset_id.value}
                for item in self.initial_portfolio
            ],
            "logical_content_hash": self.logical_content_hash.hex,
            # Include model schedule id in the completed resolved run spec semantic
            # document result.
            "model_schedule_id": (
                None if self.model_schedule_id is None else self.model_schedule_id.hex
            ),
            "network_id": self.network_id.value,
            "position_schema_id": self.position_schema_id.value,
            # Include prediction set ids in the completed resolved run spec semantic
            # document result.
            "prediction_set_ids": [item.hex for item in self.prediction_set_ids],
            "replay_contract": self.replay_contract.value,
            "replay_semantics_id": self.replay_semantics_id.hex,
            "root_seed": self.root_seed,
            "spec_version": self.spec_version,
            # Return the completed resolved run spec semantic document result without a hidden
            # fallback.
        }

    @property
    def logical_run_id(self) -> LogicalRunId:
        # Execute the resolved run spec logical run id workflow in explicit, reviewable
        # steps.
        digest = domain_digest("backtest.logical-run.v3", self.semantic_document())
        return LogicalRunId(digest.hex)

    def execution_attempt_id(
        self,
        attempt_nonce: ContentDigest,
        # Keep the physical settings digest input explicit in the execution attempt id
        # contract.
        physical_settings_digest: ContentDigest,
    ) -> ExecutionAttemptId:
        # Execute the resolved run spec execution attempt id workflow in explicit,
        # reviewable steps.
        digest = domain_digest(
            "backtest.execution-attempt.v1",
            {
                "attempt_nonce": attempt_nonce.hex,
                "delivery_schedule_id": (
                    # Pass self explicitly so domain_digest receives a reviewable v1 and
                    # attempt nonce input in resolved run spec execution attempt id.
                    None if self.delivery_schedule_id is None else self.delivery_schedule_id.hex
                ),
                "logical_run_id": self.logical_run_id.hex,
                "physical_settings_digest": physical_settings_digest.hex,
                "replay_input": self.replay_input.document(),
                # Keep runtime lock id named so the v1 and attempt nonce payload passed to
                # domain_digest remains self-describing within resolved run spec execution
                # attempt id.
                "runtime_lock_id": self.runtime_lock_id.hex,
                "snapshot_id": self.snapshot_id.hex,
            },
        )
        return ExecutionAttemptId(digest.hex)

    # Define resolved run spec execution mode as one focused operation with an explicit
    # boundary.
    def execution_mode(self) -> ExecutionMode:
        # Execute the resolved run spec execution mode workflow in explicit, reviewable
        # steps.
        component = next(item for item in self.components if item.role == "execution")
        config = cast(dict[str, Any], json.loads(component.canonical_config))
        try:
            return ExecutionMode(config["mode"])
        except (KeyError, TypeError, ValueError) as error:
            # Fail the resolved run spec execution mode path with ValueError for execution
            # component has no valid mode; do not continue ambiguously.
            raise ValueError("execution component has no valid mode") from error

    def inference_policy(self) -> ExactInferencePolicy:
        # Execute the resolved run spec inference policy workflow in explicit, reviewable
        # steps.
        component = next(item for item in self.components if item.role == "inference")
        try:
            # Perform the protected resolved run spec inference policy operation before
            # explicit failure handling.
            config = json.loads(component.canonical_config)
            return ExactInferencePolicy.from_document(config)
        except (TypeError, ValueError) as error:
            raise ValueError("inference component has no valid exact policy") from error


def dependency_merkle_root(components: tuple[ResolvedComponent, ...]) -> ContentDigest:
    # Execute the dependency merkle root workflow in explicit, reviewable steps.
    ordered = tuple(sorted(components, key=lambda item: item.role))
    if len({item.role for item in ordered}) != len(ordered):
        raise ValueError("dependency roles must be unique")
    leaves = [
        domain_digest("backtest.dependency-leaf.v1", item.identity_document()).hex
        # Keep the item component named inside the leaves contract.
        for item in ordered
    ]
    return domain_digest("backtest.dependency-merkle-root.v1", leaves)


def resolved_run_spec_bytes(spec: ResolvedRunSpec) -> bytes:
    return canonical_json_bytes(spec.document())


# Define resolved run spec from bytes as one focused operation with an explicit boundary.
def resolved_run_spec_from_bytes(payload: bytes) -> ResolvedRunSpec:
    """Decode and revalidate an exact resolved document, never a draft/alias."""

    canonical = canonicalize_job_payload(payload)
    value = json.loads(canonical)
    if not isinstance(value, dict):  # guarded by canonicalize_job_payload
        raise ValueError("resolved run document must be an object")
    document = cast(dict[str, Any], value)
    if document.get("spec_version") == 2:
        raise ReprepareRequiredError("resolved-run-spec/v2")
    if document.get("spec_version") != 3:
        # Fail the resolved run spec from bytes path with ValueError for only resolved run
        # spec version 3 is supported when get, spec version and document is true; do not
        # continue ambiguously.
        raise ValueError("only resolved run spec version 3 is supported")
    expected_keys = {
        "components",
        "dataset_revision_id",
        "delivery_schedule_id",
        # Keep the dependency merkle root component named inside the expected keys
        # contract.
        "dependency_merkle_root",
        "feature_set_ids",
        "initial_portfolio",
        "logical_content_hash",
        "model_schedule_id",
        # Keep the network id component named inside the expected keys contract.
        "network_id",
        "position_schema_id",
        "prediction_set_ids",
        "replay_contract",
        "replay_input",
        # Keep the replay semantics id component named inside the expected keys contract.
        "replay_semantics_id",
        "root_seed",
        "runtime_lock_id",
        "snapshot_id",
        "spec_id",
        # Keep the spec version component named inside the expected keys contract.
        "spec_version",
    }
    if set(document) != expected_keys:
        raise ValueError("resolved run document schema is invalid")
    components_value = document["components"]
    # Assemble replay value once so the resolved run spec from bytes workflow shares one
    # value.
    replay_value = document["replay_input"]
    balances_value = document["initial_portfolio"]
    if not isinstance(components_value, list) or not isinstance(replay_value, dict):
        raise ValueError("resolved run component or replay input schema is invalid")
    if not isinstance(balances_value, list):
        # Fail the resolved run spec from bytes path with ValueError for resolved run
        # initial portfolio must be a list when isinstance and balances value is true; do
        # not continue ambiguously.
        raise ValueError("resolved run initial portfolio must be a list")
    components = tuple(_component_from_document(item) for item in components_value)
    replay = _replay_input_from_document(cast(dict[str, object], replay_value))
    balances = tuple(_balance_from_document(item) for item in balances_value)
    feature_values = _string_list(document["feature_set_ids"], field="feature_set_ids")
    # Assemble prediction values once so the resolved run spec from bytes workflow shares
    # one value.
    prediction_values = _string_list(document["prediction_set_ids"], field="prediction_set_ids")
    model_schedule_value = document["model_schedule_id"]
    if model_schedule_value is not None and not isinstance(model_schedule_value, str):
        raise ValueError("model_schedule_id must be a digest or null")
    delivery_value = document["delivery_schedule_id"]
    # Evaluate the complete resolved run spec from bytes delivery value and isinstance
    # condition before guarded effects.
    if delivery_value is not None and not isinstance(delivery_value, str):
        raise ValueError("delivery_schedule_id must be a digest or null")
    spec_version = _strict_integer(document["spec_version"], field="spec_version")
    root_seed = _strict_integer(document["root_seed"], field="root_seed", minimum=0)
    result = ResolvedRunSpec.create(
        # Keep the network id and strict string NetworkId step visible while building
        # result.
        network_id=NetworkId(_strict_string(document, "network_id")),
        position_schema_id=PositionSchemaId(_strict_string(document, "position_schema_id")),
        dataset_revision_id=DatasetRevisionId(_strict_string(document, "dataset_revision_id")),
        logical_content_hash=LogicalContentHash(_strict_string(document, "logical_content_hash")),
        snapshot_id=SnapshotId(_strict_string(document, "snapshot_id")),
        # Keep the content digest and strict string ContentDigest step visible while
        # building result.
        replay_semantics_id=ContentDigest(_strict_string(document, "replay_semantics_id")),
        replay_input=replay,
        components=components,
        runtime_lock_id=RuntimeLockId(_strict_string(document, "runtime_lock_id")),
        initial_portfolio=balances,
        # Pass root seed explicitly so create receives a reviewable network id and
        # position schema id input in resolved run spec from bytes.
        root_seed=root_seed,
        replay_contract=ReplayContract(_strict_string(document, "replay_contract")),
        feature_set_ids=tuple(FeatureSetId(item) for item in feature_values),
        model_schedule_id=(
            None if model_schedule_value is None else ModelScheduleId(model_schedule_value)
            # Complete create only after its network id and position schema id inputs are
            # visible in resolved run spec from bytes.
        ),
        prediction_set_ids=tuple(PredictionSetId(item) for item in prediction_values),
        delivery_schedule_id=(
            None if delivery_value is None else DeliveryScheduleId(delivery_value)
        ),
        # Pass spec version explicitly so create receives a reviewable network id and
        # position schema id input in resolved run spec from bytes.
        spec_version=spec_version,
    )
    if result.spec_id != ContentDigest(_strict_string(document, "spec_id")):
        raise ValueError("resolved run spec_id differs from its canonical document")
    if result.dependency_merkle_root != ContentDigest(
        # Keep strict string visible while evaluating the dependency merkle root, result
        # and content digest guard.
        _strict_string(document, "dependency_merkle_root")
    ):
        raise ValueError("resolved dependency Merkle root differs from components")
    if result.document() != document:
        raise ValueError("resolved run document is not in exact canonical order/form")
    # Return the completed resolved run spec from bytes result without a hidden fallback.
    return result


def _component_from_document(value: object) -> ResolvedComponent:
    # Execute the component from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict):
        raise ValueError("resolved component must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {"api_version", "bundle_id", "config", "config_digest", "role"}:
        raise ValueError("resolved component schema is invalid")
    # Assemble config once so the component from document workflow shares one value.
    config = document["config"]
    if not isinstance(config, dict) or not all(isinstance(key, str) for key in config):
        raise ValueError("resolved component config must be an object")
    result = ResolvedComponent.create(
        role=_strict_string(document, "role"),
        # Keep the bundle id and strict string BundleId step visible while building
        # result.
        bundle_id=BundleId(_strict_string(document, "bundle_id")),
        config=cast(dict[str, object], config),
        api_version=_strict_integer(document["api_version"], field="api_version", minimum=1),
    )
    if result.config_digest != ContentDigest(_strict_string(document, "config_digest")):
        # Fail the component from document path with ValueError for resolved component
        # config digest mismatch when config digest, result and content digest is true; do
        # not continue ambiguously.
        raise ValueError("resolved component config digest mismatch")
    if result.identity_document() != document:
        raise ValueError("resolved component document is not canonical")
    return result


def _replay_input_from_document(document: dict[str, object]) -> ResolvedReplayInput:
    # Execute the replay input from document workflow in explicit, reviewable steps.
    if set(document) != {"format", "replay_layout_schema_id", "replay_pack_id"}:
        raise ValueError("resolved replay input schema is invalid")
    layout = document["replay_layout_schema_id"]
    pack = document["replay_pack_id"]
    if layout is not None and not isinstance(layout, str):
        # Fail the replay input from document path with ValueError for replay layout id
        # must be a digest or null when layout and isinstance is true; do not continue
        # ambiguously.
        raise ValueError("replay layout ID must be a digest or null")
    if pack is not None and not isinstance(pack, str):
        raise ValueError("replay pack ID must be a digest or null")
    return ResolvedReplayInput(
        ReplayInputFormat(_strict_string(document, "format")),
        # Include replay layout schema id in the completed replay input from document
        # result.
        replay_layout_schema_id=None if layout is None else ContentDigest(layout),
        replay_pack_id=None if pack is None else ReplayPackId(pack),
    )


def _balance_from_document(value: object) -> AssetBalance:
    # Execute the balance from document workflow in explicit, reviewable steps.
    if not isinstance(value, dict):
        raise ValueError("initial balance must be an object")
    document = cast(dict[str, object], value)
    if set(document) != {"amount_atomic", "asset_id"}:
        raise ValueError("initial balance schema is invalid")
    # Return the completed balance from document result without a hidden fallback.
    return AssetBalance(
        AssetId(_strict_string(document, "asset_id")),
        _strict_integer(document["amount_atomic"], field="amount_atomic", minimum=0),
    )


def _strict_string(document: dict[str, object], field_name: str) -> str:
    # Execute the strict string workflow in explicit, reviewable steps.
    value = document[field_name]
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    return value


def _strict_integer(value: object, *, field: str, minimum: int = 1) -> int:
    # Execute the strict integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _string_list(value: object, *, field: str) -> tuple[str, ...]:
    # Execute the string list workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return tuple(cast(list[str], value))


__all__ = [
    "AssetBalance",
    # Keep the replay contract component named inside the all contract.
    "ReplayContract",
    "ReplayInputFormat",
    "ResolvedComponent",
    "ResolvedReplayInput",
    "ResolvedRunSpec",
    # Keep the dependency merkle root component named inside the all contract.
    "dependency_merkle_root",
    "resolved_run_spec_bytes",
    "resolved_run_spec_from_bytes",
]
