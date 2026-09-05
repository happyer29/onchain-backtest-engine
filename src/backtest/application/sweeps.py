"""Immutable parameter-sweep identities and order-independent results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final, cast

from backtest.application.canonical_json import canonicalize_job_payload

# Import models at the visible module dependency boundary.
from backtest.application.models import ArtifactKind, CommittedArtifact
from backtest.application.run_results import (
    RunComparisonMetric,
    RunComparisonProjection,
    RunPhysicalSettings,
    # Include normalize comparison metrics so the run results dependency remains explicit.
    normalize_comparison_metrics,
    validate_run_warnings,
)
from backtest.application.run_specs import (
    ReplayContract,
    # Include resolved run spec so the run specs dependency remains explicit.
    ResolvedRunSpec,
    resolved_run_spec_from_bytes,
)
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ContentDigest, ExecutionAttemptId, LogicalRunId

# Bind max sweep result manifest bytes once as an explicit module-level contract.
MAX_SWEEP_RESULT_MANIFEST_BYTES: Final = 1024 * 1024


# Keep the sweep entry contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SweepEntry:
    resolved_spec: ResolvedRunSpec
    attempt_nonce: ContentDigest
    physical_settings: RunPhysicalSettings

    # Apply property semantics to the following sweep entry entry id contract.
    @property
    def entry_id(self) -> ContentDigest:
        # Execute the sweep entry entry id workflow in explicit, reviewable steps.
        return domain_digest(
            "backtest.sweep-entry.v2",
            {
                "attempt_nonce": self.attempt_nonce.hex,
                "physical_settings_digest": self.physical_settings.identity_digest.hex,
                # Keep resolved run spec id named so the v2 and attempt nonce payload
                # passed to domain_digest remains self-describing within sweep entry entry
                # id.
                "resolved_run_spec_id": self.resolved_spec.spec_id.hex,
            },
        )


# Keep the resolved sweep spec contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ResolvedSweepSpec:
    entries: tuple[SweepEntry, ...]
    comparison_metrics: tuple[RunComparisonMetric, ...] = ()

    def __post_init__(self) -> None:
        # Execute the resolved sweep spec post init workflow in explicit, reviewable
        # steps.
        if not self.entries:
            raise ValueError("a sweep requires at least one resolved run")
        ids = tuple(item.entry_id.hex for item in self.entries)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("sweep entries must be sorted and unique by entry identity")
        # Evaluate the complete resolved sweep spec post init comparison metrics and
        # normalize comparison metrics condition before guarded effects.
        if self.comparison_metrics != normalize_comparison_metrics(self.comparison_metrics):
            raise ValueError("comparison metrics must be supported, sorted and unique")

    @classmethod
    def create(
        cls,
        # Keep the entries input explicit in the create contract.
        entries: tuple[SweepEntry, ...],
        *,
        comparison_metrics: tuple[str | RunComparisonMetric, ...] = (),
    ) -> ResolvedSweepSpec:
        # Execute the resolved sweep spec create workflow in explicit, reviewable steps.
        return cls(
            tuple(sorted(entries, key=lambda item: item.entry_id.hex)),
            normalize_comparison_metrics(comparison_metrics),
        )

    @property
    # Define resolved sweep spec sweep spec id as one focused operation with an explicit
    # boundary.
    def sweep_spec_id(self) -> ContentDigest:
        # Execute the resolved sweep spec sweep spec id workflow in explicit, reviewable
        # steps.
        return domain_digest(
            "backtest.resolved-sweep-spec.v2",
            {
                "comparison_metrics": [item.value for item in self.comparison_metrics],
                "entries": [
                    # Open the v2 and comparison metrics payload explicitly for
                    # domain_digest within resolved sweep spec sweep spec id.
                    {
                        "attempt_nonce": item.attempt_nonce.hex,
                        "entry_id": item.entry_id.hex,
                        "physical_settings_digest": item.physical_settings.identity_digest.hex,
                        "resolved_run_spec_id": item.resolved_spec.spec_id.hex,
                        # Close the v2 and comparison metrics payload only after all resolved
                        # sweep spec sweep spec id fields are present.
                    }
                    for item in self.entries
                ],
            },
        )

    # Define resolved sweep spec document as one focused operation with an explicit
    # boundary.
    def document(self, *, include_spec_id: bool = True) -> dict[str, object]:
        # Execute the resolved sweep spec document workflow in explicit, reviewable steps.
        document: dict[str, object] = {
            "comparison_metrics": [item.value for item in self.comparison_metrics],
            "entries": [
                {
                    "attempt_nonce": item.attempt_nonce.hex,
                    # Register document and physical settings through document so the
                    # document table remains scannable.
                    "physical_settings": item.physical_settings.document(),
                    "resolved_run_spec": item.resolved_spec.document(),
                }
                for item in self.entries
            ],
            # Keep the spec version component named inside the document contract.
            "spec_version": 2,
        }
        if include_spec_id:
            document["sweep_spec_id"] = self.sweep_spec_id.hex
        return document


# Keep the sweep entry result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SweepEntryResult:
    entry_id: ContentDigest
    logical_run_id: LogicalRunId
    execution_attempt_id: ExecutionAttemptId
    # Declare canonical result hash explicitly in the sweep entry result contract.
    canonical_result_hash: ContentDigest
    run_artifact: CommittedArtifact
    comparison: RunComparisonProjection
    physical_settings: RunPhysicalSettings
    canonicality: ReplayContract
    # Declare warnings explicitly in the sweep entry result contract.
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        # Execute the sweep entry result post init workflow in explicit, reviewable steps.
        if self.run_artifact.kind is not ArtifactKind.RUN:
            raise ValueError("a sweep entry must retain a committed Run artifact")
        if self.canonical_result_hash != self.comparison.canonical_result_hash:
            raise ValueError("sweep result hash differs from its comparison projection")
        if self.canonicality is not ReplayContract.CANONICAL_EXACT:
            # Fail the sweep entry result post init path with ValueError for a successful
            # sweep entry must be canonical exact when canonicality, canonical exact and
            # replay contract is true; do not continue ambiguously.
            raise ValueError("a successful sweep entry must be CANONICAL_EXACT")
        validate_run_warnings(self.warnings)

    def document(
        self,
        comparison_metrics: tuple[RunComparisonMetric, ...],
        # Keep the dict input explicit in the document contract.
    ) -> dict[str, object]:
        # Execute the sweep entry result document workflow in explicit, reviewable steps.
        return {
            "canonical_result_hash": self.canonical_result_hash.hex,
            "canonicality": self.canonicality.value,
            "comparison": self.comparison.selected_document(comparison_metrics),
            "entry_id": self.entry_id.hex,
            # Include execution attempt id in the completed sweep entry result document
            # result.
            "execution_attempt_id": self.execution_attempt_id.hex,
            "logical_run_id": self.logical_run_id.hex,
            "physical_settings": self.physical_settings.document(),
            "run_artifact_id": self.run_artifact.artifact_id.hex,
            "warnings": list(self.warnings),
            # Return the completed sweep entry result document result without a hidden
            # fallback.
        }


# Keep the sweep result contract and validation rules together.
@dataclass(frozen=True, slots=True)
class SweepResult:
    sweep_spec_id: ContentDigest
    comparison_metrics: tuple[RunComparisonMetric, ...]
    entries: tuple[SweepEntryResult, ...]
    # Declare artifact explicitly in the sweep result contract.
    artifact: CommittedArtifact

    def __post_init__(self) -> None:
        # Execute the sweep result post init workflow in explicit, reviewable steps.
        ids = tuple(item.entry_id.hex for item in self.entries)
        if not self.entries or ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("sweep results must be non-empty, sorted and unique")
        if self.comparison_metrics != normalize_comparison_metrics(self.comparison_metrics):
            raise ValueError("sweep result metrics must be supported, sorted and unique")
        # Evaluate the complete sweep result post init kind, sweep and artifact condition
        # before guarded effects.
        if self.artifact.kind is not ArtifactKind.SWEEP:
            raise ValueError("sweep result must reference a committed SWEEP artifact")
        expected_inputs = tuple(
            sorted(
                (item.run_artifact.artifact_id for item in self.entries),
                # Pass key explicitly so sorted receives a reviewable artifact id and run
                # artifact input in sweep result post init.
                key=lambda item: item.hex,
            )
        )
        if self.artifact.input_artifact_ids != expected_inputs:
            raise ValueError("sweep artifact must retain every exact run artifact")

    # Apply property semantics to the following sweep result result digest contract.
    @property
    def result_digest(self) -> ContentDigest:
        return sweep_result_digest(self.sweep_spec_id, self.comparison_metrics, self.entries)


def sweep_result_digest(
    sweep_spec_id: ContentDigest,
    # Keep the comparison metrics input explicit in the sweep result digest contract.
    comparison_metrics: tuple[RunComparisonMetric, ...],
    entries: tuple[SweepEntryResult, ...],
) -> ContentDigest:
    # Execute the sweep result digest workflow in explicit, reviewable steps.
    if comparison_metrics != normalize_comparison_metrics(comparison_metrics):
        raise ValueError("sweep result metrics must be supported, sorted and unique")
    entry_ids = tuple(item.entry_id.hex for item in entries)
    if (
        not entries
        # Keep entry ids visible while evaluating the entries, entry ids and sorted guard.
        or entry_ids != tuple(sorted(entry_ids))
        or len(entry_ids) != len(set(entry_ids))
    ):
        raise ValueError("sweep digest entries must be non-empty, sorted and unique")
    return domain_digest(
        # Pass version tag explicitly so domain_digest receives a reviewable v2 and
        # comparison metrics input in sweep result digest.
        "backtest.sweep-result.v2",
        {
            "comparison_metrics": [item.value for item in comparison_metrics],
            "entries": [item.document(comparison_metrics) for item in entries],
            "sweep_spec_id": sweep_spec_id.hex,
            # Close the v2 and comparison metrics payload only after all sweep result digest
            # fields are present.
        },
    )


def resolved_sweep_spec_bytes(value: ResolvedSweepSpec) -> bytes:
    return canonical_json_bytes(value.document())


def resolved_sweep_spec_from_bytes(payload: bytes) -> ResolvedSweepSpec:
    # Execute the resolved sweep spec from bytes workflow in explicit, reviewable steps.
    canonical = canonicalize_job_payload(payload)
    if canonical != payload:
        raise ValueError("ResolvedSweepSpec must use canonical JSON")
    document = cast(dict[str, Any], json.loads(payload))
    if set(document) != {"comparison_metrics", "entries", "spec_version", "sweep_spec_id"}:
        # Fail the resolved sweep spec from bytes path with ValueError for resolved sweep
        # spec schema is invalid when document, comparison metrics and entries is true; do
        # not continue ambiguously.
        raise ValueError("ResolvedSweepSpec schema is invalid")
    if document["spec_version"] != 2:
        raise ValueError("unsupported ResolvedSweepSpec version; expected version 2")
    raw_entries = document["entries"]
    raw_metrics = document["comparison_metrics"]
    # Evaluate the complete resolved sweep spec from bytes isinstance, raw entries and raw
    # metrics condition before guarded effects.
    if not isinstance(raw_entries, list) or not isinstance(raw_metrics, list):
        raise ValueError("ResolvedSweepSpec entries and metrics must be lists")
    entries: list[SweepEntry] = []
    for raw in raw_entries:
        # Process raw_entries inside the bounded resolved sweep spec from bytes loop.
        if not isinstance(raw, dict) or set(raw) != {
            "attempt_nonce",
            "physical_settings",
            "resolved_run_spec",
        }:
            # Fail the resolved sweep spec from bytes path with ValueError for resolved
            # sweep spec entry schema is invalid when isinstance, raw and attempt nonce is
            # true; do not continue ambiguously.
            raise ValueError("ResolvedSweepSpec entry schema is invalid")
        nonce = raw["attempt_nonce"]
        physical = raw["physical_settings"]
        nested = raw["resolved_run_spec"]
        if not isinstance(nonce, str) or not isinstance(nested, dict):
            # Fail the resolved sweep spec from bytes path with ValueError for resolved
            # sweep spec entry fields are invalid when isinstance, nonce and nested is
            # true; do not continue ambiguously.
            raise ValueError("ResolvedSweepSpec entry fields are invalid")
        entries.append(
            SweepEntry(
                resolved_run_spec_from_bytes(canonical_json_bytes(nested)),
                ContentDigest(nonce),
                # Pass run physical settings explicitly to append for from document and
                # sweep entry.
                RunPhysicalSettings.from_document(physical),
            )
        )
    if not all(isinstance(item, str) for item in raw_metrics):
        raise ValueError("comparison metrics must be strings")
    # Assemble result once so the resolved sweep spec from bytes workflow shares one
    # value.
    result = ResolvedSweepSpec.create(
        tuple(entries),
        comparison_metrics=tuple(cast(list[str], raw_metrics)),
    )
    stored_id = document["sweep_spec_id"]
    # Evaluate the complete resolved sweep spec from bytes sweep spec id, isinstance and
    # stored id condition before guarded effects.
    if not isinstance(stored_id, str) or ContentDigest(stored_id) != result.sweep_spec_id:
        raise ValueError("ResolvedSweepSpec identity does not match its document")
    if result.document() != document:
        raise ValueError("ResolvedSweepSpec does not round-trip exactly")
    return result


# Bind all once as an explicit module-level contract.
__all__ = [
    "MAX_SWEEP_RESULT_MANIFEST_BYTES",
    "ResolvedSweepSpec",
    "RunComparisonMetric",
    "SweepEntry",
    # Keep the sweep entry result component named inside the all contract.
    "SweepEntryResult",
    "SweepResult",
    "resolved_sweep_spec_bytes",
    "resolved_sweep_spec_from_bytes",
    "sweep_result_digest",
    # Complete the all group only after its semantic components are visible.
]
