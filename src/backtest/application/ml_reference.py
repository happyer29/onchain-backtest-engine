"""Secret-free description of the installed exact reference ML vertical slice."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.domain.identifiers import BundleId, ContentDigest, RuntimeLockId


# Keep the reference ml contract contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ReferenceMlContract:
    runtime_lock_id: RuntimeLockId
    compiler_version: str
    feature_builder_bundle_id: BundleId
    # Declare supported feature names explicitly in the reference ml contract contract.
    supported_feature_names: tuple[str, ...]
    universe_builder_bundle_id: BundleId
    universe_spec_id: ContentDigest
    universe_config_digest: ContentDigest
    label_builder_bundle_id: BundleId
    # Declare label spec id explicitly in the reference ml contract contract.
    label_spec_id: ContentDigest
    label_config_digest: ContentDigest
    trainer_bundle_id: BundleId
    trainer_framework: str
    frozen_inference_bundle_id: BundleId

    # Define reference ml contract post init as one focused operation with an explicit
    # boundary.
    def __post_init__(self) -> None:
        # Execute the reference ml contract post init workflow in explicit, reviewable
        # steps.
        for field in ("compiler_version", "trainer_framework"):
            # Process compiler version and trainer framework inside the bounded reference
            # ml contract post init loop.
            value = str(getattr(self, field))
            if not value or value != value.strip() or "\x00" in value:
                raise ValueError(f"{field} must be non-empty, trimmed and NUL-free")
        if not self.supported_feature_names or self.supported_feature_names != tuple(
            sorted(set(self.supported_feature_names))
            # Complete tuple only after its supported feature names and sorted inputs are
            # visible in reference ml contract post init.
        ):
            raise ValueError("supported feature names must be sorted, unique and non-empty")


__all__ = ["ReferenceMlContract"]
