"""Source-enabled child composition used only by exact prepare-dataset jobs."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from backtest.adapters.artifacts.localfs import LocalArtifactRepository

# Import arrow at the visible module dependency boundary.
from backtest.adapters.columnar.arrow import LocalArrowCanonicalStore
from backtest.adapters.source.clickhouse import (
    ClickHouseCapability,
    clickhouse_capability_mapping_digest,
    load_clickhouse_capabilities,
    # Close the clickhouse import after its required symbols are visible.
)
from backtest.adapters.source.clickhouse.query import query_template_digest
from backtest.application.job_commands import ReusableCanonicalDistribution
from backtest.application.models import DatasetPlan
from backtest.application.ports.source import SourceMetadataReader

# Import source fingerprint at the visible module dependency boundary.
from backtest.application.source_fingerprint import source_schema_fingerprint
from backtest.application.use_cases.prepare_dataset import PrepareDataset
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import ConfigError, Settings
from backtest.bootstrap.configured_projector import build_configured_projector
from backtest.bootstrap.pumpfun_live_source import build_pumpfun_live_source_composition

# Import source at the visible module dependency boundary.
from backtest.bootstrap.source import ConfiguredClickHouseSource, select_clickhouse_query_profile
from backtest.domain.identifiers import ContentDigest
from backtest.runtime.thread_limits import apply_thread_limits


class PreparationPreflightError(RuntimeError):
    """A resolved extraction cannot safely start against the current source."""


class SourceMetadataPreflightError(PreparationPreflightError):
    """Fresh, bounded source metadata could not be inspected safely."""


class SourceSchemaDriftError(PreparationPreflightError):
    """Fresh source metadata differs from the exact planned inspection."""


@dataclass(frozen=True, slots=True)
class PreparationContainer:
    settings: Settings
    artifacts: LocalArtifactRepository
    capabilities: tuple[ClickHouseCapability, ...]
    # Declare source metadata explicitly in the preparation container contract.
    source_metadata: SourceMetadataReader
    prepare_dataset: PrepareDataset
    projector_digest: ContentDigest
    source_normalizer_digest: ContentDigest | None

    def validate_plan(self, plan: DatasetPlan) -> None:
        # Execute the preparation container validate plan workflow in explicit, reviewable
        # steps.
        spec = plan.spec
        if spec.source_id.value != self.settings.source.source_id:
            raise ValueError("resolved dataset plan targets another source")
        if spec.capability_mapping_digest != clickhouse_capability_mapping_digest(
            self.capabilities
            # Complete clickhouse_capability_mapping_digest only after its capabilities inputs
            # are visible in preparation container validate plan.
        ):
            raise ValueError("resolved dataset plan uses another capability mapping")
        profile = select_clickhouse_query_profile(self.capabilities)
        expected_query_digest = (
            query_template_digest() if profile is None else profile.template_digest
        )
        if spec.query_template_digest != expected_query_digest:
            raise ValueError("resolved dataset plan uses another query template")
        source_binding = spec.source_evidence_binding
        if source_binding is not None:
            if source_binding.projector_digest != self.projector_digest:
                raise ValueError("resolved dataset plan uses another canonical projector")
            if source_binding.normalizer_digest != self.source_normalizer_digest:
                raise ValueError("resolved dataset plan uses another source normalizer")

    def validate_execution(
        # Keep the remaining validate execution inputs visible at the preparation
        # container validate execution boundary.
        self,
        plan: DatasetPlan,
        reusable_distributions: tuple[ReusableCanonicalDistribution, ...],
    ) -> None:
        """Fail before extraction if a required remote scan sees schema drift.

        A fully reused plan is intentionally offline-capable: every selected
        distribution is reopened and reverified by the canonical store, so no
        remote metadata connection is required.  Any missing shard, however,
        requires one fresh metadata inspection before the first scan or
        staging publication.
        """

        self.validate_plan(plan)
        reused_ordinals = {item.shard_ordinal for item in reusable_distributions}
        planned_ordinals = {item.ordinal for item in plan.spec.shards}
        if reused_ordinals == planned_ordinals:
            return

        # Assemble metadata once so the preparation container validate execution workflow
        # shares one value.
        metadata = None
        with suppress(Exception):
            metadata = self.source_metadata.inspect_metadata(plan.spec.source_id)
        # Driver errors may contain a credential-bearing URL.  Leave the
        # exception scope before raising the stable public failure.
        if metadata is None:
            # Handle the preparation container validate execution metadata is None branch
            # as a distinct logical block.
            raise SourceMetadataPreflightError(
                "fresh source metadata preflight failed before extraction"
            )
        spec = plan.spec
        if (
            # Keep metadata visible while evaluating the source id, capability mapping
            # digest and query template digest guard.
            metadata.source_id != spec.source_id
            or metadata.capability_mapping_digest != spec.capability_mapping_digest
            or metadata.query_template_digest != spec.query_template_digest
            or source_schema_fingerprint(metadata) != spec.source_schema_fingerprint
        ):
            # Handle the preparation container validate execution source id, capability
            # mapping digest and query template digest condition as a distinct block.
            raise SourceSchemaDriftError(
                "fresh source schema differs from the resolved dataset plan"
            )


def build_preparation_container(
    settings: Settings,
    # Close the build preparation container signature after its explicit inputs.
    *,
    capabilities_file: Path | None = None,
) -> PreparationContainer:
    """Wire the sole child mode permitted to open the read-only remote source."""

    selected_capabilities = capabilities_file or settings.source.capabilities_file
    if selected_capabilities is None or settings.source.projections_file is None:
        raise ConfigError("prepare-dataset requires capability and projection configuration")
    resources = settings.resources
    apply_thread_limits(resources.native_threads_per_process)
    # Assemble capabilities once so the build preparation container workflow shares one
    # value.
    capabilities = load_clickhouse_capabilities(selected_capabilities)
    profile = select_clickhouse_query_profile(capabilities)
    pumpfun_live = None if profile is None else build_pumpfun_live_source_composition(capabilities)
    projection_capabilities = (
        capabilities if pumpfun_live is None else pumpfun_live.projection_capabilities
    )
    build_tools = BuildToolBundleRegistry().pin()
    projector = build_configured_projector(
        settings.source.projections_file,
        projection_capabilities,
        # Pass build tools explicitly so build_configured_projector receives a reviewable
        # projections file and source input in build preparation container.
        build_tools=build_tools,
        source_normalizer_digest=(None if pumpfun_live is None else pumpfun_live.normalizer_digest),
    )
    artifacts = LocalArtifactRepository(
        settings.paths.data_root.resolve(),
        staging_quota_bytes=resources.tmp_quota_gb * 1024**3,
        # Complete LocalArtifactRepository only after its resolve and data root inputs are
        # visible in build preparation container.
    )
    source = ConfiguredClickHouseSource(
        settings,
        capabilities,
        pumpfun_live=pumpfun_live,
        projector_digest=(None if pumpfun_live is None else projector.config_digest),
    )
    store = LocalArrowCanonicalStore(
        artifacts,
        memory_limit_mb=resources.max_builder_memory_mb,
        # Pass threads explicitly so LocalArrowCanonicalStore receives a reviewable max
        # builder memory mb and native threads per process input in build preparation
        # container.
        threads=resources.native_threads_per_process,
        tmp_quota_bytes=resources.tmp_quota_gb * 1024**3,
        build_tools=build_tools,
    )
    return PreparationContainer(
        # Pass settings explicitly so PreparationContainer receives a reviewable prepare
        # dataset and settings input in build preparation container.
        settings=settings,
        artifacts=artifacts,
        capabilities=capabilities,
        source_metadata=source,
        prepare_dataset=PrepareDataset(source, projector, store),
        projector_digest=projector.config_digest,
        source_normalizer_digest=(None if pumpfun_live is None else pumpfun_live.normalizer_digest),
        # Complete PreparationContainer only after its prepare dataset and settings inputs are
        # visible in build preparation container.
    )


__all__ = [
    "PreparationContainer",
    "PreparationPreflightError",
    "SourceMetadataPreflightError",
    # Keep the source schema drift error component named inside the all contract.
    "SourceSchemaDriftError",
    "build_preparation_container",
]
