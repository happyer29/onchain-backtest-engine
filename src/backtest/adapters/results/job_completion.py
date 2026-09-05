"""Strict typed read-back for successful isolated-job artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from backtest.application.attempt_identity import (
    # Include queued execution attempt nonce so the attempt identity dependency remains
    # explicit.
    queued_execution_attempt_nonce,
    queued_sweep_entry_attempt_nonce,
)
from backtest.application.canonical_data import (
    CanonicalDistributionRef,
    # Include effective source boundary so the canonical data dependency remains explicit.
    EffectiveSourceBoundary,
    PreparedSnapshot,
    ValidationStatus,
    canonical_distribution_source_contract,
)

# Import dataset plans at the visible module dependency boundary.
from backtest.application.dataset_plans import dataset_spec_document
from backtest.application.delivery_schedules import (
    CompiledDeliverySchedule,
    DeliveryScheduleManifest,
)

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import (
    ResolvedBacktestJob,
    ResolvedCompileDeliveryScheduleJob,
    ResolvedCompileReplayJob,
    ResolvedPrepareDatasetJob,
    # Include resolved sweep job so the job commands dependency remains explicit.
    ResolvedSweepJob,
    run_input_artifact_ids,
)
from backtest.application.models import (
    ArtifactKind,
    # Include attempt state so the models dependency remains explicit.
    AttemptState,
    CommittedArtifact,
    DatasetPlan,
    DatasetShard,
    JobAttempt,
    # Include job type so the models dependency remains explicit.
    JobType,
    PlannedCapability,
)
from backtest.application.ports.artifacts import ArtifactRepository
from backtest.application.replay_packs import CompiledReplayPack, ReplayPackManifest

# Import run results at the visible module dependency boundary.
from backtest.application.run_results import (
    MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
    SuccessfulRunManifest,
    successful_run_manifest_from_bytes,
)

# Import sweeps at the visible module dependency boundary.
from backtest.application.sweeps import (
    MAX_SWEEP_RESULT_MANIFEST_BYTES,
    SweepEntryResult,
    SweepResult,
    sweep_result_digest,
    # Close the sweeps import after its required symbols are visible.
)
from backtest.application.use_cases.run_backtest import RunBacktestResult
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    # Include bundle id so the identifiers dependency remains explicit.
    BundleId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    DeliveryScheduleId,
    # Include execution attempt id so the identifiers dependency remains explicit.
    ExecutionAttemptId,
    LogicalContentHash,
    LogicalRunId,
    ReplayPackId,
    SnapshotId,
    # Include source id so the identifiers dependency remains explicit.
    SourceId,
)
from backtest.domain.market_events import EventKind
from backtest.domain.time import BlockRange
from backtest.engine.rng import RNG_ALGORITHM


# Keep the local job result error contract and validation rules together.
class LocalJobResultError(RuntimeError):
    """A committed child result does not satisfy its type-specific contract."""


class LocalJobResultReader:
    """Reconstruct application results without re-running a heavy use case."""

    def __init__(self, artifacts: ArtifactRepository) -> None:
        self._artifacts = artifacts

    def prepared_snapshot(
        self,
        command: ResolvedPrepareDatasetJob,
        # Keep the artifact input explicit in the prepared snapshot contract.
        artifact: CommittedArtifact,
    ) -> PreparedSnapshot:
        # Execute the local job result reader prepared snapshot workflow in explicit,
        # reviewable steps.
        if artifact.kind is not ArtifactKind.SNAPSHOT:
            raise LocalJobResultError("prepare result is not a snapshot")
        document = self._manifest(artifact)
        _keys(
            document,
            # Open the artifact schema and capability ranges payload explicitly for _keys
            # within local job result reader prepared snapshot.
            {
                "artifact_schema",
                "capability_ranges",
                "canonical_schema_version",
                "created_at",
                # Pass dataset revision id explicitly so _keys receives a reviewable
                # artifact schema and capability ranges input in local job result reader
                # prepared snapshot.
                "dataset_revision_id",
                "dataset_spec",
                "distributions",
                "logical_content_hash",
                "network_id",
                # Pass position schema id explicitly so _keys receives a reviewable
                # artifact schema and capability ranges input in local job result reader
                # prepared snapshot.
                "position_schema_id",
                "projector_bundle_id",
                "requested_decision_range",
                "settlement_tail",
                "source_boundaries",
                # Pass source id explicitly so _keys receives a reviewable artifact schema
                # and capability ranges input in local job result reader prepared
                # snapshot.
                "source_id",
                "spec_id",
                "validation_status",
            },
            "snapshot manifest",
            # Complete _keys only after its artifact schema and capability ranges inputs are
            # visible in local job result reader prepared snapshot.
        )
        plan = command.plan
        if (
            document["artifact_schema"] != "canonical-snapshot/v4"
            or document["canonical_schema_version"] != 3
            # Keep document visible while evaluating the value, hex and document guard.
            or document["validation_status"] != ValidationStatus.PASS.value
            or document["source_id"] != plan.spec.source_id.value
            or document["spec_id"] != plan.spec.spec_id.hex
            or document["network_id"] != plan.spec.network_id.value
            or document["position_schema_id"] != plan.spec.position_schema_id.value
            # Keep document visible while evaluating the value, hex and document guard.
            or document["dataset_spec"] != dataset_spec_document(plan.spec)
            or document["requested_decision_range"] != _range_document(plan.spec.decision_range)
            or document["settlement_tail"]
            != (
                None
                # Keep plan visible while evaluating the value, hex and document guard.
                if plan.spec.settlement_tail is None
                else _range_document(plan.spec.settlement_tail)
            )
            or document["capability_ranges"]
            != [
                # Evaluate the complete local job result reader prepared snapshot value,
                # hex and document condition before guarded effects.
                {
                    "block_range": _range_document(item.block_range),
                    "capability_id": item.capability_id.value,
                }
                for item in plan.spec.capability_ranges
                # Evaluate the complete local job result reader prepared snapshot value, hex
                # and document condition before guarded effects.
            ]
        ):
            raise LocalJobResultError("snapshot manifest differs from its resolved plan")
        projector_bundle_id = BundleId(_string(document["projector_bundle_id"], "projector"))
        distribution_values = _list(document["distributions"], "distributions")
        # Assemble boundary values once so the local job result reader prepared snapshot
        # workflow shares one value.
        boundary_values = _list(document["source_boundaries"], "source boundaries")
        if len(distribution_values) != len(plan.spec.shards) or len(boundary_values) != len(
            plan.spec.shards
        ):
            raise LocalJobResultError("snapshot does not cover every resolved shard")
        # Assemble distributions once so the local job result reader prepared snapshot
        # workflow shares one value.
        distributions = tuple(
            self._distribution(
                _object(value, "snapshot distribution"),
                plan=plan,
                shard=shard,
                # Keep the capabilities _capability step visible while building
                # distributions.
                capability=_capability(plan.spec.capabilities, shard.capability_id),
                projector_bundle_id=projector_bundle_id,
                source_id=plan.spec.source_id,
            )
            for value, shard in zip(distribution_values, plan.spec.shards, strict=True)
            # Complete tuple only after its snapshot distribution and distribution inputs are
            # visible in local job result reader prepared snapshot.
        )
        referenced_ids = tuple(
            sorted(
                (item.artifact.artifact_id for item in distributions),
                key=lambda item: item.hex,
                # Complete sorted only after its artifact id and artifact inputs are visible
                # in local job result reader prepared snapshot.
            )
        )
        if referenced_ids != artifact.input_artifact_ids:
            raise LocalJobResultError("snapshot descriptor differs from distribution references")
        if [
            # Keep item visible while evaluating the boundary values, identity document
            # and item guard.
            item.effective_source_boundary.identity_document()
            for item in distributions
        ] != boundary_values:
            raise LocalJobResultError("snapshot source boundaries differ from its partitions")
        if any(
            # Pass distributions explicitly so any receives a reviewable artifact id and
            # reusable distributions input in local job result reader prepared snapshot.
            distributions[item.shard_ordinal].artifact.artifact_id != item.artifact_id
            # Pass item explicitly so any receives a reviewable artifact id and reusable
            # distributions input in local job result reader prepared snapshot.
            for item in command.reusable_distributions
        ):
            raise LocalJobResultError("snapshot did not preserve an exact resolved reuse input")
        snapshot_id = SnapshotId(artifact.artifact_id.hex)
        return PreparedSnapshot(
            # Pass artifact explicitly so PreparedSnapshot receives a reviewable dataset
            # revision and dataset revision id input in local job result reader prepared
            # snapshot.
            artifact=artifact,
            snapshot_id=snapshot_id,
            dataset_revision_id=DatasetRevisionId(
                _string(document["dataset_revision_id"], "dataset revision")
            ),
            # Include logical content hash in the completed local job result reader
            # prepared snapshot result.
            logical_content_hash=LogicalContentHash(
                _string(document["logical_content_hash"], "logical content hash")
            ),
            spec=plan.spec,
            projector_bundle_id=projector_bundle_id,
            # Pass distributions explicitly so PreparedSnapshot receives a reviewable
            # dataset revision and dataset revision id input in local job result reader
            # prepared snapshot.
            distributions=distributions,
            extracted_at=_timestamp(document["created_at"], "snapshot created_at"),
        )

    def compiled_replay(
        self,
        # Keep the command input explicit in the compiled replay contract.
        command: ResolvedCompileReplayJob,
        artifact: CommittedArtifact,
    ) -> CompiledReplayPack:
        # Execute the local job result reader compiled replay workflow in explicit,
        # reviewable steps.
        if artifact.kind is not ArtifactKind.REPLAY_PACK:
            raise LocalJobResultError("compile result is not a ReplayPack")
        manifest = ReplayPackManifest.from_document(self._manifest(artifact))
        if (
            manifest.snapshot_id != command.snapshot_id
            # Keep manifest visible while evaluating the snapshot id, compiler version and
            # input artifact ids guard.
            or manifest.build.snapshot_id != command.snapshot_id
            or manifest.build.compiler_version != command.compiler_version
            or artifact.input_artifact_ids != (ArtifactId(command.snapshot_id.hex),)
        ):
            raise LocalJobResultError("ReplayPack differs from its resolved compile command")
        # Return the completed local job result reader compiled replay result without a
        # hidden fallback.
        return CompiledReplayPack(
            artifact,
            ReplayPackId(artifact.artifact_id.hex),
            manifest,
            manifest.build,
            # Complete CompiledReplayPack only after its hex and artifact id inputs are
            # visible in local job result reader compiled replay.
        )

    def compiled_delivery_schedule(
        self,
        command: ResolvedCompileDeliveryScheduleJob,
        artifact: CommittedArtifact,
        # Keep the compiled delivery schedule input explicit in the compiled delivery schedule
        # contract.
    ) -> CompiledDeliverySchedule:
        # Execute the local job result reader compiled delivery schedule workflow in
        # explicit, reviewable steps.
        if artifact.kind is not ArtifactKind.DELIVERY_SCHEDULE:
            raise LocalJobResultError("compile result is not a DeliverySchedule")
        manifest = DeliveryScheduleManifest.from_document(self._manifest(artifact))
        spec = command.resolved_spec
        replay_pack_id = spec.replay_input.replay_pack_id
        # Assemble replay layout id once so the local job result reader compiled delivery
        # schedule workflow shares one value.
        replay_layout_id = spec.replay_input.replay_layout_schema_id
        expected_components = tuple(
            item
            for item in spec.components
            if item.role in {"clock", "engine", "latency", "scheduler"}
            # Complete tuple only after its clock and engine inputs are visible in local job
            # result reader compiled delivery schedule.
        )
        if (
            replay_pack_id is None
            or replay_layout_id is None
            or manifest.replay_pack_id != replay_pack_id
            # Keep manifest visible while evaluating the replay pack id, replay layout id
            # and replay semantics id guard.
            or manifest.replay_semantics_id != spec.replay_semantics_id
            or manifest.replay_layout_schema_id != replay_layout_id
            or manifest.build.components != expected_components
            or manifest.build.root_seed != spec.root_seed
            or manifest.build.rng_algorithm != RNG_ALGORITHM
            # Keep manifest visible while evaluating the replay pack id, replay layout id
            # and replay semantics id guard.
            or manifest.build.compiler_version != command.compiler_version
            or artifact.input_artifact_ids != (ArtifactId(replay_pack_id.hex),)
        ):
            raise LocalJobResultError("DeliverySchedule differs from its resolved compile command")
        return CompiledDeliverySchedule(
            # Pass artifact explicitly so CompiledDeliverySchedule receives a reviewable
            # hex and artifact id input in local job result reader compiled delivery
            # schedule.
            artifact,
            DeliveryScheduleId(artifact.artifact_id.hex),
            manifest,
            manifest.build,
        )

    # Define local job result reader successful run manifest as one focused operation with
    # an explicit boundary.
    def successful_run_manifest(self, artifact_id: ArtifactId) -> SuccessfulRunManifest:
        """Re-open and strictly reconstruct one exact committed Run seed."""

        return self._successful_run_manifest(self._descriptor(artifact_id))

    def run_result(
        self,
        command: ResolvedBacktestJob,
        artifact: CommittedArtifact,
        # Keep the attempt input explicit in the run result contract.
        attempt: JobAttempt | None = None,
    ) -> RunBacktestResult:
        # Execute the local job result reader run result workflow in explicit, reviewable
        # steps.
        expected_nonce = command.attempt_nonce
        if attempt is not None:
            # Handle the local job result reader run result attempt is not None branch as
            # a distinct logical block.
            _require_attempt(attempt, JobType.RUN_BACKTEST, command.canonical_bytes())
            expected_nonce = queued_execution_attempt_nonce(
                command.attempt_nonce,
                attempt.attempt_id,
                attempt.spec.spec_id,
                # Complete queued_execution_attempt_nonce only after its attempt nonce and
                # attempt id inputs are visible in local job result reader run result.
            )
        manifest = self._successful_run_manifest(artifact)
        if (
            manifest.resolved_spec != command.resolved_spec
            or manifest.physical_settings != command.physical_settings
            # Keep manifest visible while evaluating the resolved spec, physical settings
            # and attempt nonce guard.
            or manifest.attempt_nonce != expected_nonce
            or manifest.input_artifact_ids != run_input_artifact_ids(command.resolved_spec)
        ):
            raise LocalJobResultError("run artifact differs from its resolved command")
        return RunBacktestResult(
            # Pass logical run id explicitly so RunBacktestResult receives a reviewable
            # logical run id and execution attempt id input in local job result reader run
            # result.
            logical_run_id=manifest.logical_run_id,
            execution_attempt_id=manifest.execution_attempt_id,
            canonical_result_hash=manifest.summary.result_hash,
            artifact=artifact,
            comparison=manifest.comparison,
            # Pass physical settings explicitly so RunBacktestResult receives a reviewable
            # logical run id and execution attempt id input in local job result reader run
            # result.
            physical_settings=manifest.physical_settings,
            canonicality=manifest.canonicality,
            warnings=manifest.warnings,
        )

    def sweep_result(
        # Keep the remaining sweep result inputs visible at the local job result reader
        # sweep result boundary.
        self,
        command: ResolvedSweepJob,
        artifact: CommittedArtifact,
        attempt: JobAttempt | None = None,
    ) -> SweepResult:
        # Execute the local job result reader sweep result workflow in explicit,
        # reviewable steps.
        attempt_namespace = None
        if attempt is not None:
            # Handle the local job result reader sweep result attempt is not None branch
            # as a distinct logical block.
            _require_attempt(attempt, JobType.RUN_SWEEP, command.canonical_bytes())
            attempt_namespace = queued_execution_attempt_nonce(
                ContentDigest(command.resolved_sweep_spec.sweep_spec_id.hex),
                attempt.attempt_id,
                attempt.spec.spec_id,
                # Complete queued_execution_attempt_nonce only after its hex and sweep spec id
                # inputs are visible in local job result reader sweep result.
            )
        if artifact.kind is not ArtifactKind.SWEEP:
            raise LocalJobResultError("sweep result has the wrong artifact kind")
        document = self._manifest(
            artifact,
            # Pass maximum bytes explicitly so _manifest receives a reviewable artifact
            # and max sweep result manifest bytes input in local job result reader sweep
            # result.
            maximum_bytes=MAX_SWEEP_RESULT_MANIFEST_BYTES,
            require_canonical=True,
        )
        _keys(
            document,
            # Open the comparison metrics and entries payload explicitly for _keys within
            # local job result reader sweep result.
            {
                "comparison_metrics",
                "entries",
                "result_digest",
                "schema",
                # Pass sweep spec id explicitly so _keys receives a reviewable comparison
                # metrics and entries input in local job result reader sweep result.
                "sweep_spec_id",
            },
            "sweep result",
        )
        spec = command.resolved_sweep_spec
        # Evaluate the complete local job result reader sweep result hex, document and
        # schema condition before guarded effects.
        if (
            document["schema"] != "backtest.sweep-result/v2"
            or document["sweep_spec_id"] != spec.sweep_spec_id.hex
            or document["comparison_metrics"] != [item.value for item in spec.comparison_metrics]
        ):
            # Fail the local job result reader sweep result path with LocalJobResultError
            # for sweep manifest differs from its resolved spec when hex, document and
            # schema is true; do not continue ambiguously.
            raise LocalJobResultError("sweep manifest differs from its resolved spec")
        expected = {item.entry_id.hex: item for item in spec.entries}
        values = _list(document["entries"], "sweep entries")
        if len(values) != len(expected):
            raise LocalJobResultError("sweep result count differs from its resolved spec")
        # Assemble entries once so the local job result reader sweep result workflow
        # shares one value.
        entries: list[SweepEntryResult] = []
        for value in values:
            # Process values inside the bounded local job result reader sweep result loop.
            entry_document = _object(value, "sweep entry result")
            _keys(
                entry_document,
                {
                    "canonical_result_hash",
                    # Pass canonicality explicitly so _keys receives a reviewable
                    # canonical result hash and canonicality input in local job result
                    # reader sweep result.
                    "canonicality",
                    "comparison",
                    "entry_id",
                    "execution_attempt_id",
                    "logical_run_id",
                    # Pass physical settings explicitly so _keys receives a reviewable
                    # canonical result hash and canonicality input in local job result
                    # reader sweep result.
                    "physical_settings",
                    "run_artifact_id",
                    "warnings",
                },
                "sweep entry result",
                # Complete _keys only after its canonical result hash and canonicality inputs
                # are visible in local job result reader sweep result.
            )
            entry_id = ContentDigest(_string(entry_document["entry_id"], "entry ID"))
            try:
                resolved_entry = expected[entry_id.hex]
            except KeyError as error:
                # Fail the local job result reader sweep result path with
                # LocalJobResultError for sweep contains an unresolved entry; do not
                # continue ambiguously.
                raise LocalJobResultError("sweep contains an unresolved entry") from error
            run_artifact = self._descriptor(
                ArtifactId(_string(entry_document["run_artifact_id"], "run artifact ID"))
            )
            run_manifest = self._successful_run_manifest(run_artifact)
            # Assemble expected nonce once so the local job result reader sweep result
            # workflow shares one value.
            expected_nonce = queued_sweep_entry_attempt_nonce(
                resolved_entry.attempt_nonce,
                resolved_entry.entry_id,
                attempt_namespace,
            )
            # Assemble expected physical once so the local job result reader sweep result
            # workflow shares one value.
            expected_physical = resolved_entry.physical_settings
            canonical_result_hash = ContentDigest(
                _string(entry_document["canonical_result_hash"], "canonical result hash")
            )
            execution_attempt_id = ExecutionAttemptId(
                # Keep the string and entry document _string step visible while building
                # execution attempt id.
                _string(entry_document["execution_attempt_id"], "execution attempt ID")
            )
            logical_run_id = LogicalRunId(
                _string(entry_document["logical_run_id"], "logical run ID")
            )
            # Evaluate the complete local job result reader sweep result resolved spec,
            # attempt nonce and expected nonce condition before guarded effects.
            if (
                run_manifest.resolved_spec != resolved_entry.resolved_spec
                or run_manifest.attempt_nonce != expected_nonce
                or run_manifest.physical_settings != expected_physical
                or run_manifest.input_artifact_ids
                # Keep run input artifact ids visible while evaluating the resolved spec,
                # attempt nonce and expected nonce guard.
                != run_input_artifact_ids(resolved_entry.resolved_spec)
                or run_manifest.summary.result_hash != canonical_result_hash
                or run_manifest.execution_attempt_id != execution_attempt_id
                or run_manifest.logical_run_id != logical_run_id
                or entry_document["canonicality"] != run_manifest.canonicality.value
                # Keep entry document visible while evaluating the resolved spec, attempt
                # nonce and expected nonce guard.
                or entry_document["physical_settings"] != run_manifest.physical_settings.document()
                or entry_document["warnings"] != list(run_manifest.warnings)
                or entry_document["comparison"]
                != run_manifest.comparison.selected_document(spec.comparison_metrics)
            ):
                # Fail the local job result reader sweep result path with
                # LocalJobResultError for sweep entry differs from its committed run when
                # resolved spec, attempt nonce and expected nonce is true; do not continue
                # ambiguously.
                raise LocalJobResultError("sweep entry differs from its committed run")
            entries.append(
                SweepEntryResult(
                    entry_id,
                    logical_run_id,
                    # Pass execution attempt id explicitly so SweepEntryResult receives a
                    # reviewable comparison and physical settings input in local job
                    # result reader sweep result.
                    execution_attempt_id,
                    canonical_result_hash,
                    run_artifact,
                    run_manifest.comparison,
                    run_manifest.physical_settings,
                    # Pass run manifest explicitly so SweepEntryResult receives a
                    # reviewable comparison and physical settings input in local job
                    # result reader sweep result.
                    run_manifest.canonicality,
                    run_manifest.warnings,
                )
            )
        normalized = tuple(sorted(entries, key=lambda item: item.entry_id.hex))
        # Assemble result once so the local job result reader sweep result workflow shares
        # one value.
        result = SweepResult(spec.sweep_spec_id, spec.comparison_metrics, normalized, artifact)
        stored_digest = ContentDigest(_string(document["result_digest"], "result digest"))
        if stored_digest != sweep_result_digest(
            spec.sweep_spec_id,
            spec.comparison_metrics,
            # Pass normalized explicitly so sweep_result_digest receives a reviewable
            # sweep spec id and comparison metrics input in local job result reader sweep
            # result.
            normalized,
        ):
            raise LocalJobResultError("sweep result digest does not match its entries")
        return result

    def _distribution(
        # Keep the remaining distribution inputs visible at the local job result reader
        # distribution boundary.
        self,
        reference: dict[str, object],
        *,
        plan: DatasetPlan,
        shard: DatasetShard,
        # Keep the capability input explicit in the distribution contract.
        capability: PlannedCapability,
        projector_bundle_id: BundleId,
        source_id: SourceId,
    ) -> CanonicalDistributionRef:
        # Execute the local job result reader distribution workflow in explicit,
        # reviewable steps.
        _keys(
            reference,
            {
                "artifact_id",
                "capability_id",
                # Pass event kind explicitly so _keys receives a reviewable artifact id
                # and capability id input in local job result reader distribution.
                "event_kind",
                "logical_content_hash",
                "manifest_digest",
                "row_count",
                "shard",
                # Close the artifact id and capability id payload only after all local job
                # result reader distribution fields are present.
            },
            "snapshot distribution reference",
        )
        if reference["shard"] != _shard_document(shard):
            raise LocalJobResultError("snapshot distribution references another shard")
        # Assemble artifact once so the local job result reader distribution workflow
        # shares one value.
        artifact = self._descriptor(
            ArtifactId(_string(reference["artifact_id"], "distribution artifact ID"))
        )
        if artifact.kind is not ArtifactKind.CANONICAL_DISTRIBUTION:
            raise LocalJobResultError("snapshot input is not a canonical distribution")
        # Assemble manifest once so the local job result reader distribution workflow
        # shares one value.
        manifest = self._manifest(artifact)
        _keys(
            manifest,
            {
                "artifact_schema",
                # Pass canonical schema id explicitly so _keys receives a reviewable
                # artifact schema and canonical schema id input in local job result reader
                # distribution.
                "canonical_schema_id",
                "canonical_schema_version",
                "capability_id",
                "created_at",
                "event_file",
                # Pass event kind explicitly so _keys receives a reviewable artifact
                # schema and canonical schema id input in local job result reader
                # distribution.
                "event_kind",
                "logical_content_hash",
                "maximum_boundary_ordinal",
                "minimum_boundary_ordinal",
                "network_id",
                # Pass position schema id explicitly so _keys receives a reviewable
                # artifact schema and canonical schema id input in local job result reader
                # distribution.
                "position_schema_id",
                "projector_bundle_id",
                "row_count",
                "source_boundary",
                "source_contract",
                # Pass writer bundle id explicitly so _keys receives a reviewable artifact
                # schema and canonical schema id input in local job result reader
                # distribution.
                "writer_bundle_id",
            },
            "canonical distribution manifest",
        )
        logical_hash = LogicalContentHash(
            # Keep the string and reference _string step visible while building logical
            # hash.
            _string(reference["logical_content_hash"], "distribution logical hash")
        )
        row_count = _integer(reference["row_count"], "distribution row count")
        event_kind_name = _string(reference["event_kind"], "event kind")
        try:
            # Assemble event kind once so the local job result reader distribution
            # workflow shares one value.
            event_kind = EventKind[event_kind_name]
        except KeyError as error:
            raise LocalJobResultError("distribution event kind is unsupported") from error
        if (
            reference["capability_id"] != shard.capability_id.value
            # Keep reference visible while evaluating the value, hex and parquet guard.
            or reference["manifest_digest"] != artifact.manifest_digest.hex
            or manifest["artifact_schema"] != "canonical-distribution/v5"
            or manifest["canonical_schema_version"] != 3
            or manifest["event_file"] != "events.parquet"
            or manifest["capability_id"] != shard.capability_id.value
            # Keep manifest visible while evaluating the value, hex and parquet guard.
            or manifest["event_kind"] != event_kind.name
            or manifest["logical_content_hash"] != logical_hash.hex
            or manifest["row_count"] != row_count
            or manifest["projector_bundle_id"] != projector_bundle_id.hex
            or manifest["network_id"] != plan.spec.network_id.value
            # Keep manifest visible while evaluating the value, hex and parquet guard.
            or manifest["position_schema_id"] != plan.spec.position_schema_id.value
            or manifest["source_contract"]
            != canonical_distribution_source_contract(
                plan,
                shard,
                # Pass capability explicitly so canonical_distribution_source_contract
                # receives a reviewable plan and shard input in local job result reader
                # distribution.
                capability,
            )
            or artifact.input_artifact_ids != (plan.spec.source_inspection_artifact_id,)
        ):
            raise LocalJobResultError("canonical distribution differs from snapshot reference")
        # Keep expected failures inside the local job result reader distribution error
        # boundary.
        try:
            effective_boundary = EffectiveSourceBoundary.from_document(manifest["source_boundary"])
        except ValueError as error:
            raise LocalJobResultError("distribution source boundary is invalid") from error
        boundary = effective_boundary.source_boundary
        # Assemble fidelity once so the local job result reader distribution workflow
        # shares one value.
        fidelity = effective_boundary.source_fidelity
        if (
            boundary.source_id != source_id
            or boundary.capability_id != shard.capability_id
            or boundary.capability_schema_version != capability.schema_version
            # Keep boundary visible while evaluating the source id, capability id and
            # capability schema version guard.
            or boundary.block_range != shard.block_range
            or effective_boundary.event_kind is not event_kind
            or fidelity.identity is not capability.fidelity.identity
            or fidelity.ordering is not capability.fidelity.ordering
            or fidelity.state is not capability.fidelity.state
            # Keep fidelity visible while evaluating the source id, capability id and
            # capability schema version guard.
            or fidelity.fees is not capability.fidelity.fees
        ):
            raise LocalJobResultError("distribution boundary differs from its resolved shard")
        _timestamp(manifest["created_at"], "distribution created_at")
        return CanonicalDistributionRef(
            # Pass artifact explicitly so CanonicalDistributionRef receives a reviewable
            # minimum boundary and minimum boundary ordinal input in local job result
            # reader distribution.
            artifact=artifact,
            logical_content_hash=logical_hash,
            capability_id=shard.capability_id,
            event_kind=event_kind,
            shard=shard,
            # Pass row count explicitly so CanonicalDistributionRef receives a reviewable
            # minimum boundary and minimum boundary ordinal input in local job result
            # reader distribution.
            row_count=row_count,
            minimum_boundary_ordinal=_optional_integer(
                manifest["minimum_boundary_ordinal"], "minimum boundary"
            ),
            maximum_boundary_ordinal=_optional_integer(
                # Pass manifest explicitly so _optional_integer receives a reviewable
                # maximum boundary ordinal and maximum boundary input in local job result
                # reader distribution.
                manifest["maximum_boundary_ordinal"],
                "maximum boundary",
            ),
            source_boundary=boundary,
            source_fidelity=fidelity,
            # Complete CanonicalDistributionRef only after its minimum boundary and minimum
            # boundary ordinal inputs are visible in local job result reader distribution.
        )

    # Define local job result reader successful run manifest as one focused operation with
    # an explicit boundary.
    def _successful_run_manifest(
        self,
        artifact: CommittedArtifact,
    ) -> SuccessfulRunManifest:
        # Execute the local job result reader successful run manifest workflow in
        # explicit, reviewable steps.
        if artifact.kind is not ArtifactKind.RUN:
            raise LocalJobResultError("result is not a committed Run artifact")
        try:
            # Perform the protected local job result reader successful run manifest
            # operation before explicit failure handling.
            manifest = successful_run_manifest_from_bytes(
                self._manifest_bytes(
                    artifact,
                    maximum_bytes=MAX_SUCCESSFUL_RUN_MANIFEST_BYTES,
                )
                # Complete successful_run_manifest_from_bytes only after its manifest bytes
                # and artifact inputs are visible in local job result reader successful run
                # manifest.
            )
        except (TypeError, ValueError) as error:
            raise LocalJobResultError("successful run manifest is invalid") from error
        if artifact.input_artifact_ids != manifest.input_artifact_ids:
            raise LocalJobResultError("run descriptor differs from its manifest")
        # Return the completed local job result reader successful run manifest result
        # without a hidden fallback.
        return manifest

    def _manifest(
        self,
        expected: CommittedArtifact,
        *,
        # Keep the maximum bytes input explicit in the manifest contract.
        maximum_bytes: int | None = None,
        require_canonical: bool = False,
    ) -> dict[str, object]:
        # Execute the local job result reader manifest workflow in explicit, reviewable
        # steps.
        payload = self._manifest_bytes(expected, maximum_bytes=maximum_bytes)
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, ValueError) as error:
            raise LocalJobResultError("committed result manifest is invalid JSON") from error
        # Assemble document once so the local job result reader manifest workflow shares
        # one value.
        document = _object(value, "committed result manifest")
        if require_canonical:
            # Handle the local job result reader manifest require_canonical branch as a
            # distinct logical block.
            try:
                canonical = canonical_json_bytes(document)
            except (TypeError, ValueError) as error:
                # Translate the (TypeError, ValueError) failure through the local job
                # result reader manifest boundary.
                raise LocalJobResultError(
                    "committed result manifest cannot be canonicalized"
                ) from error
            if canonical != payload:
                raise LocalJobResultError("committed result manifest is not canonical JSON")
        # Return the completed local job result reader manifest result without a hidden
        # fallback.
        return document

    def _manifest_bytes(
        self,
        expected: CommittedArtifact,
        *,
        # Keep the maximum bytes input explicit in the manifest bytes contract.
        maximum_bytes: int | None = None,
    ) -> bytes:
        # Execute the local job result reader manifest bytes workflow in explicit,
        # reviewable steps.
        handle = self._artifacts.open_committed(expected.artifact_id)
        try:
            # Perform the protected local job result reader manifest bytes operation
            # before explicit failure handling.
            if handle.descriptor != expected:
                raise LocalJobResultError("committed descriptor changed during result read-back")
            with handle.open_binary("manifest.json") as stream:
                payload = stream.read(-1 if maximum_bytes is None else maximum_bytes + 1)
        finally:
            # Invoke close as a visible step within the local job result reader manifest
            # bytes workflow.
            handle.close()
        if maximum_bytes is not None and len(payload) > maximum_bytes:
            raise LocalJobResultError("committed result manifest exceeds its bounded limit")
        return payload

    def _descriptor(self, artifact_id: ArtifactId) -> CommittedArtifact:
        # Execute the local job result reader descriptor workflow in explicit, reviewable
        # steps.
        handle = self._artifacts.open_committed(artifact_id)
        try:
            return handle.descriptor
        finally:
            handle.close()


# Define require attempt as one focused operation with an explicit boundary.
def _require_attempt(
    attempt: JobAttempt,
    expected_type: JobType,
    expected_payload: bytes,
) -> None:
    # Execute the require attempt workflow in explicit, reviewable steps.
    if (
        attempt.state is not AttemptState.SUCCEEDED
        or attempt.spec.job_type is not expected_type
        or attempt.spec.canonical_payload != expected_payload
    ):
        # Fail the require attempt path with LocalJobResultError for successful attempt
        # differs from its resolved command when state, succeeded and job type is true; do
        # not continue ambiguously.
        raise LocalJobResultError("successful attempt differs from its resolved command")


def _capability(
    capabilities: tuple[PlannedCapability, ...], capability_id: CapabilityId
) -> PlannedCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    matches = tuple(item for item in capabilities if item.capability_id == capability_id)
    if len(matches) != 1:
        raise LocalJobResultError("resolved shard has no unique planned capability")
    return matches[0]


def _shard_document(shard: DatasetShard) -> dict[str, object]:
    # Execute the shard document workflow in explicit, reviewable steps.
    return {
        "block_range": _range_document(shard.block_range),
        "capability_id": shard.capability_id.value,
        "columns": list(shard.columns),
        "ordinal": shard.ordinal,
        # Return the completed shard document result without a hidden fallback.
    }


def _range_document(value: BlockRange) -> dict[str, object]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


def _timestamp(value: object, field: str) -> datetime:
    # Execute the timestamp workflow in explicit, reviewable steps.
    raw = _string(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise LocalJobResultError(f"{field} is not an ISO timestamp") from error
    # Evaluate the complete timestamp tzinfo, parsed and utcoffset condition before
    # guarded effects.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LocalJobResultError(f"{field} must be timezone-aware")
    return parsed


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LocalJobResultError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _list(value: object, field: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise LocalJobResultError(f"{field} must be a list")
    return cast(list[object], value)


def _keys(document: dict[str, object], expected: set[str], field: str) -> None:
    # Execute the keys workflow in explicit, reviewable steps.
    if set(document) != expected:
        raise LocalJobResultError(f"{field} schema is invalid")


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise LocalJobResultError(f"{field} must be a non-empty trimmed string")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LocalJobResultError(f"{field} must be an integer >= {minimum}")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


# Bind all once as an explicit module-level contract.
__all__ = ["LocalJobResultError", "LocalJobResultReader"]
