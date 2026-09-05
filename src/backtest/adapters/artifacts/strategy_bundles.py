"""Verified local publication of inert strategy bundle archives."""

from __future__ import annotations

from hashlib import sha256

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.application.strategy_bundles import (
    # Include published strategy bundle so the strategy bundles dependency remains
    # explicit.
    PublishedStrategyBundle,
    StrategyBundleManifest,
    strategy_bundle_manifest_from_bytes,
)
from backtest.domain.identifiers import ArtifactId, BundleId, ContentDigest


# Keep the strategy bundle integrity error contract and validation rules together.
class StrategyBundleIntegrityError(RuntimeError):
    """Bundle bytes or metadata do not match the exact declared package."""


class LocalStrategyBundleStore:
    def __init__(self, artifacts: LocalArtifactRepository) -> None:
        self._artifacts = artifacts

    def publish(
        self,
        # Keep the manifest input explicit in the publish contract.
        manifest: StrategyBundleManifest,
        code_archive: bytes,
    ) -> PublishedStrategyBundle:
        # Execute the local strategy bundle store publish workflow in explicit, reviewable
        # steps.
        if sha256(code_archive).hexdigest() != manifest.code_digest.hex:
            raise StrategyBundleIntegrityError("strategy archive digest differs from manifest")
        writer = self._artifacts.stage(
            ArtifactDraft(ArtifactKind.STRATEGY_BUNDLE, manifest.build_key)
        )
        # Keep expected failures inside the local strategy bundle store publish error
        # boundary.
        try:
            # Perform the protected local strategy bundle store publish operation before
            # explicit failure handling.
            with writer.open_binary("bundle.bin") as stream:
                stream.write(code_archive)
            committed = writer.commit(
                manifest.manifest_bytes(),
                identity_manifest_bytes=manifest.manifest_bytes(),
                # Complete commit only after its manifest bytes and manifest inputs are
                # visible in local strategy bundle store publish.
            )
        except BaseException:
            # Translate the BaseException failure through the local strategy bundle store
            # publish boundary.
            writer.abort()
            raise
        return PublishedStrategyBundle(
            BundleId(committed.artifact_id.hex),
            committed,
            # Include self in the completed local strategy bundle store publish result.
            self.open(BundleId(committed.artifact_id.hex)).manifest,
        )

    def open(self, bundle_id: BundleId) -> PublishedStrategyBundle:
        # Execute the local strategy bundle store open workflow in explicit, reviewable
        # steps.
        handle = self._artifacts.open_committed(ArtifactId(bundle_id.hex))
        try:
            # Perform the protected local strategy bundle store open operation before
            # explicit failure handling.
            if handle.descriptor.kind is not ArtifactKind.STRATEGY_BUNDLE:
                raise StrategyBundleIntegrityError("requested artifact is not a strategy bundle")
            with handle.open_binary("manifest.json") as stream:
                manifest = strategy_bundle_manifest_from_bytes(stream.read())
            with handle.open_binary("bundle.bin") as stream:
                # Assemble actual once so the local strategy bundle store open workflow
                # shares one value.
                actual = ContentDigest(sha256(stream.read()).hexdigest())
            if actual != manifest.code_digest:
                raise StrategyBundleIntegrityError("strategy archive failed verification")
            return PublishedStrategyBundle(bundle_id, handle.descriptor, manifest)
        finally:
            # Invoke close as a visible step within the local strategy bundle store open
            # workflow.
            handle.close()


__all__ = ["LocalStrategyBundleStore", "StrategyBundleIntegrityError"]
