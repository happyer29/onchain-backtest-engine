"""Immutable strategy package metadata resolved before a run is queued."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.models import CommittedArtifact
from backtest.domain.execution import ExecutionMode
from backtest.domain.fidelity import (
    ChainFinality,
    # Include fees fidelity so the fidelity dependency remains explicit.
    FeesFidelity,
    FidelityRequirement,
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    # Include source consistency so the fidelity dependency remains explicit.
    SourceConsistency,
    StateFidelity,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import BundleId, ContentDigest, RuntimeLockId


# Keep the strategy resource class contract and validation rules together.
class StrategyResourceClass(StrEnum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


# Keep the strategy bundle manifest contract and validation rules together.
@dataclass(frozen=True, slots=True)
class StrategyBundleManifest:
    api_version: int
    code_digest: ContentDigest
    package_format: str
    # Declare config schema json explicitly in the strategy bundle manifest contract.
    config_schema_json: bytes
    default_config_json: bytes
    requirements: tuple[str, ...]
    dependency_lock_digest: ContentDigest
    runtime_compatibility_id: RuntimeLockId
    # Declare tests digest explicitly in the strategy bundle manifest contract.
    tests_digest: ContentDigest
    golden_metadata_digest: ContentDigest
    subscriptions: tuple[str, ...]
    minimum_fidelity: FidelityRequirement
    supported_execution_modes: tuple[ExecutionMode, ...]
    # Declare estimated dynamic state bytes explicitly in the strategy bundle manifest
    # contract.
    estimated_dynamic_state_bytes: int
    resource_class: StrategyResourceClass
    load_policy: str = "composition-root-allowlist-only-v1"

    def __post_init__(self) -> None:
        # Execute the strategy bundle manifest post init workflow in explicit, reviewable
        # steps.
        if self.api_version <= 0:
            raise ValueError("strategy API version must be positive")
        for field in ("package_format", "load_policy"):
            # Process ('package_format', 'load_policy') inside the bounded strategy bundle
            # manifest post init loop.
            value = str(getattr(self, field))
            if not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{field} must be non-empty, trimmed and NUL-free")
        schema = canonicalize_job_payload(self.config_schema_json)
        defaults = canonicalize_job_payload(self.default_config_json)
        # Evaluate the complete strategy bundle manifest post init schema, config schema
        # json and defaults condition before guarded effects.
        if schema != self.config_schema_json or defaults != self.default_config_json:
            raise ValueError("strategy schema and defaults must be canonical JSON objects")
        for field, values in (
            ("requirements", self.requirements),
            ("subscriptions", self.subscriptions),
            # Traverse requirements and subscriptions explicitly so each strategy bundle
            # manifest post init iteration remains traceable.
        ):
            # Process requirements and subscriptions inside the bounded strategy bundle
            # manifest post init loop.
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field} must be sorted and unique")
            if any(not item or item != item.strip() or "\x00" in item for item in values):
                raise ValueError(f"{field} contains an invalid value")
        modes = tuple(sorted(set(self.supported_execution_modes), key=lambda item: item.value))
        # Evaluate the complete strategy bundle manifest post init modes and supported
        # execution modes condition before guarded effects.
        if not modes or modes != self.supported_execution_modes:
            raise ValueError("supported execution modes must be sorted, unique and non-empty")
        if self.estimated_dynamic_state_bytes < 0:
            raise ValueError("estimated dynamic strategy state must be non-negative")

    def identity_document(self) -> dict[str, object]:
        # Execute the strategy bundle manifest identity document workflow in explicit,
        # reviewable steps.
        return {
            "api_version": self.api_version,
            "code_digest": self.code_digest.hex,
            "config_schema": cast(dict[str, object], json.loads(self.config_schema_json)),
            "default_config": cast(dict[str, object], json.loads(self.default_config_json)),
            # Include dependency lock digest in the completed strategy bundle manifest
            # identity document result.
            "dependency_lock_digest": self.dependency_lock_digest.hex,
            "estimated_dynamic_state_bytes": self.estimated_dynamic_state_bytes,
            "golden_metadata_digest": self.golden_metadata_digest.hex,
            "load_policy": self.load_policy,
            "minimum_fidelity": _fidelity_document(self.minimum_fidelity),
            # Include package format in the completed strategy bundle manifest identity
            # document result.
            "package_format": self.package_format,
            "requirements": list(self.requirements),
            "resource_class": self.resource_class.value,
            "runtime_compatibility_id": self.runtime_compatibility_id.hex,
            "subscriptions": list(self.subscriptions),
            # Include supported execution modes in the completed strategy bundle manifest
            # identity document result.
            "supported_execution_modes": [item.value for item in self.supported_execution_modes],
            "tests_digest": self.tests_digest.hex,
        }

    @property
    def build_key(self) -> ContentDigest:
        # Return the completed strategy bundle manifest build key result without a hidden
        # fallback.
        return domain_digest("backtest.strategy-bundle-build.v1", self.identity_document())

    def manifest_bytes(self) -> bytes:
        # Execute the strategy bundle manifest manifest bytes workflow in explicit,
        # reviewable steps.
        return canonical_json_bytes(
            {"artifact_schema": "strategy-bundle/v1", **self.identity_document()}
        )


# Keep the published strategy bundle contract and validation rules together.
@dataclass(frozen=True, slots=True)
class PublishedStrategyBundle:
    bundle_id: BundleId
    artifact: CommittedArtifact
    manifest: StrategyBundleManifest

    # Define published strategy bundle post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the published strategy bundle post init workflow in explicit, reviewable
        # steps.
        if self.bundle_id.hex != self.artifact.artifact_id.hex:
            raise ValueError("strategy bundle ID must equal its committed artifact ID")


def strategy_bundle_manifest_from_bytes(payload: bytes) -> StrategyBundleManifest:
    # Execute the strategy bundle manifest from bytes workflow in explicit, reviewable
    # steps.
    canonical = canonicalize_job_payload(payload)
    if canonical != payload:
        raise ValueError("strategy manifest must be canonical JSON")
    value = cast(dict[str, Any], json.loads(payload))
    expected = {
        # Keep the api version component named inside the expected contract.
        "api_version",
        "artifact_schema",
        "code_digest",
        "config_schema",
        "default_config",
        # Keep the dependency lock digest component named inside the expected contract.
        "dependency_lock_digest",
        "estimated_dynamic_state_bytes",
        "golden_metadata_digest",
        "load_policy",
        "minimum_fidelity",
        # Keep the package format component named inside the expected contract.
        "package_format",
        "requirements",
        "resource_class",
        "runtime_compatibility_id",
        "subscriptions",
        # Keep the supported execution modes component named inside the expected contract.
        "supported_execution_modes",
        "tests_digest",
    }
    if set(value) != expected or value["artifact_schema"] != "strategy-bundle/v1":
        raise ValueError("strategy manifest schema is invalid")
    # Assemble fidelity once so the strategy bundle manifest from bytes workflow shares
    # one value.
    fidelity = value["minimum_fidelity"]
    if not isinstance(fidelity, dict) or set(fidelity) != {
        "chain_finality",
        "completeness",
        "consistency",
        # Keep fees visible while evaluating the isinstance, fidelity and chain finality
        # guard.
        "fees",
        "identity",
        "ordering",
        "state",
    }:
        # Fail the strategy bundle manifest from bytes path with ValueError for strategy
        # fidelity schema is invalid when isinstance, fidelity and chain finality is true;
        # do not continue ambiguously.
        raise ValueError("strategy fidelity schema is invalid")
    try:
        # Perform the protected strategy bundle manifest from bytes operation before
        # explicit failure handling.
        result = StrategyBundleManifest(
            api_version=_integer(value["api_version"], "api_version"),
            code_digest=ContentDigest(_string(value["code_digest"], "code_digest")),
            package_format=_string(value["package_format"], "package_format"),
            config_schema_json=canonical_json_bytes(_object(value["config_schema"], "schema")),
            # Keep the canonical json bytes and object canonical_json_bytes step visible
            # while building result.
            default_config_json=canonical_json_bytes(_object(value["default_config"], "defaults")),
            requirements=_strings(value["requirements"], "requirements"),
            dependency_lock_digest=ContentDigest(
                _string(value["dependency_lock_digest"], "dependency_lock_digest")
            ),
            # Keep the runtime lock id and string RuntimeLockId step visible while
            # building result.
            runtime_compatibility_id=RuntimeLockId(
                _string(value["runtime_compatibility_id"], "runtime_compatibility_id")
            ),
            tests_digest=ContentDigest(_string(value["tests_digest"], "tests_digest")),
            golden_metadata_digest=ContentDigest(
                # Keep the string and golden metadata digest _string step visible while
                # building result.
                _string(value["golden_metadata_digest"], "golden_metadata_digest")
            ),
            subscriptions=_strings(value["subscriptions"], "subscriptions"),
            minimum_fidelity=FidelityRequirement(
                identity=IdentityFidelity(_string(fidelity["identity"], "identity")),
                # Keep the ordering fidelity and string OrderingFidelity step visible
                # while building result.
                ordering=OrderingFidelity(_string(fidelity["ordering"], "ordering")),
                state=StateFidelity(_string(fidelity["state"], "state")),
                fees=FeesFidelity(_string(fidelity["fees"], "fees")),
                chain_finality=ChainFinality(_string(fidelity["chain_finality"], "chain_finality")),
                completeness=IngestionCompleteness(
                    # Keep the string and completeness _string step visible while building
                    # result.
                    _string(fidelity["completeness"], "completeness")
                ),
                consistency=SourceConsistency(_string(fidelity["consistency"], "consistency")),
            ),
            supported_execution_modes=tuple(
                # Keep the sorted and execution mode sorted step visible while building
                # result.
                sorted(
                    (
                        ExecutionMode(item)
                        for item in _strings(
                            value["supported_execution_modes"],
                            # Pass supported execution modes explicitly so _strings
                            # receives a reviewable supported execution modes and value
                            # input in strategy bundle manifest from bytes.
                            "supported_execution_modes",
                            # Complete _strings only after its supported execution modes and
                            # value inputs are visible in strategy bundle manifest from bytes.
                        )
                    ),
                    key=lambda item: item.value,
                )
            ),
            # Keep the integer and estimated dynamic state bytes _integer step visible
            # while building result.
            estimated_dynamic_state_bytes=_integer(
                value["estimated_dynamic_state_bytes"], "estimated_dynamic_state_bytes", minimum=0
            ),
            resource_class=StrategyResourceClass(
                _string(value["resource_class"], "resource_class")
                # Complete StrategyResourceClass only after its resource class and string
                # inputs are visible in strategy bundle manifest from bytes.
            ),
            load_policy=_string(value["load_policy"], "load_policy"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("strategy manifest contains an invalid field") from error
    # Guard this path with result.manifest_bytes() != payload before applying effects.
    if result.manifest_bytes() != payload:
        raise ValueError("strategy manifest does not round-trip exactly")
    return result


def _fidelity_document(value: FidelityRequirement) -> dict[str, str]:
    # Execute the fidelity document workflow in explicit, reviewable steps.
    return {
        "chain_finality": value.chain_finality.value,
        "completeness": value.completeness.value,
        "consistency": value.consistency.value,
        "fees": value.fees.value,
        # Include identity in the completed fidelity document result.
        "identity": value.identity.value,
        "ordering": value.ordering.value,
        "state": value.state.value,
    }


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value


def _integer(value: object, field: str, *, minimum: int = 1) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _strings(value: object, field: str) -> tuple[str, ...]:
    # Execute the strings workflow in explicit, reviewable steps.
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field} must be a string list")
    return tuple(cast(list[str], value))


__all__ = [
    "PublishedStrategyBundle",
    # Keep the strategy bundle manifest component named inside the all contract.
    "StrategyBundleManifest",
    "StrategyResourceClass",
    "strategy_bundle_manifest_from_bytes",
]
