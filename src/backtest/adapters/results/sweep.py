"""Immutable aggregate publication for one resolved parameter sweep."""

from __future__ import annotations

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.models import ArtifactDraft, ArtifactKind, CommittedArtifact
from backtest.application.sweeps import (
    MAX_SWEEP_RESULT_MANIFEST_BYTES,
    # Include resolved sweep spec so the sweeps dependency remains explicit.
    ResolvedSweepSpec,
    SweepEntryResult,
    sweep_result_digest,
)
from backtest.domain.hashing import canonical_json_bytes


# Keep the local sweep output store contract and validation rules together.
class LocalSweepOutputStore:
    """Publish one canonical comparison manifest retaining all exact run roots."""

    def __init__(self, artifacts: LocalArtifactRepository) -> None:
        self._artifacts = artifacts

    def publish(
        self,
        spec: ResolvedSweepSpec,
        # Keep the entries input explicit in the publish contract.
        entries: tuple[SweepEntryResult, ...],
    ) -> CommittedArtifact:
        # Execute the local sweep output store publish workflow in explicit, reviewable
        # steps.
        if not entries:
            raise ValueError("a sweep output requires at least one run result")
        if tuple(sorted(entries, key=lambda item: item.entry_id.hex)) != entries:
            raise ValueError("sweep output entries must be canonically ordered")
        input_ids = tuple(
            # Keep the sorted and artifact id sorted step visible while building input
            # ids.
            sorted(
                (item.run_artifact.artifact_id for item in entries),
                key=lambda item: item.hex,
            )
        )
        # Guard this path with len(input_ids) != len(set(input_ids)) before applying
        # effects.
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("sweep entries must have distinct run artifacts")
        result_digest = sweep_result_digest(
            spec.sweep_spec_id,
            spec.comparison_metrics,
            # Pass entries explicitly so sweep_result_digest receives a reviewable sweep
            # spec id and comparison metrics input in local sweep output store publish.
            entries,
        )
        document = {
            "comparison_metrics": [item.value for item in spec.comparison_metrics],
            "entries": [item.document(spec.comparison_metrics) for item in entries],
            # Keep the result digest component named inside the document contract.
            "result_digest": result_digest.hex,
            "schema": "backtest.sweep-result/v2",
            "sweep_spec_id": spec.sweep_spec_id.hex,
        }
        payload = canonical_json_bytes(document)
        # Evaluate the complete local sweep output store publish max sweep result manifest
        # bytes and payload condition before guarded effects.
        if len(payload) > MAX_SWEEP_RESULT_MANIFEST_BYTES:
            raise ValueError("sweep result exceeds the bounded metadata limit")
        writer = self._artifacts.stage(
            ArtifactDraft(
                kind=ArtifactKind.SWEEP,
                # Pass build key explicitly so ArtifactDraft receives a reviewable sweep
                # and sweep spec id input in local sweep output store publish.
                build_key=spec.sweep_spec_id,
                input_artifact_ids=input_ids,
            )
        )
        try:
            # Perform the protected local sweep output store publish operation before
            # explicit failure handling.
            with writer.open_binary("comparison.json") as stream:
                stream.write(payload)
            return writer.commit(payload, identity_manifest_bytes=payload)
        except BaseException:
            # Translate the BaseException failure through the local sweep output store
            # publish boundary.
            writer.abort()
            raise


__all__ = ["LocalSweepOutputStore"]
