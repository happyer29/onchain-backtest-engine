"""Coordinate a research consumer without granting it execution authority."""

import json
from dataclasses import dataclass

# Application coordination depends on ports, with no source credentials or native engines.
from backtest.application.models import AttemptState, CommittedArtifact, JobType
from backtest.application.ports.research import ResearchJobQuery, ResearchSource, ResearchStore
from backtest.application.research import (
    MAX_PAGE_SIZE,
    # Immutable research contracts remain structurally separate from executable replay specs.
    ResearchDatasetSpec,
    ResearchError,
    # Shared command parsing preserves CLI/API/child identity across transport forms.
    ResearchTable,
    WalletAnalysisSpec,
    # Primitive validation prevents lossy transport values from reaching a reader.
    analysis_spec,
    dataset_spec,
    integer,
)
from backtest.domain.chain import BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID

# Identity and canonical serializers remain owned by the core.
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId, NetworkId, SourceId
from backtest.domain.time import BlockRange


@dataclass(frozen=True, slots=True)
class PrepareResearch:
    """Inspect the fixed schema before allowing a bounded source scan to publish."""

    source: ResearchSource
    store: ResearchStore

    def execute(self, spec: ResearchDatasetSpec) -> CommittedArtifact:
        """A schema rejection happens before any source observation is streamed."""
        schema = self.source.inspect(spec)
        return self.store.publish_snapshot(spec, schema, self.source.batches(spec))


@dataclass(frozen=True, slots=True)
class ResearchUseCases:
    """Shared CLI/API resolution and bounded views; heavy work is queued separately."""

    store: ResearchStore
    code_digest: ContentDigest
    runtime_digest: ContentDigest
    profile_digest: ContentDigest
    source_id: SourceId
    # Network comes from the installed mapping, never a mutable mainnet alias.
    network_id: NetworkId | None
    jobs: ResearchJobQuery | None = None

    def job_result(self, job_id: JobId) -> ArtifactId:
        """Bind successful operational state to the exact verified research manifest."""

        if self.jobs is None:
            raise ResearchError("RESEARCH_JOB_QUERY_UNAVAILABLE")
        job = self.jobs.get_job(job_id)
        if job is None or job.state is not AttemptState.SUCCEEDED:
            raise ResearchError("RESEARCH_JOB_NOT_SUCCEEDED")
        # SQLite locates a candidate; the store must independently verify its committed bytes.
        result = self.jobs.get_successful_result(job_id)
        if result is None:
            raise ResearchError("RESEARCH_JOB_RESULT_MISSING")
        summary = self.summary(result)
        field = "dataset" if job.spec.job_type is JobType.PREPARE_RESEARCH else "analysis"
        # A backtest result or another successful research command cannot satisfy this job.
        if job.spec.job_type not in {JobType.PREPARE_RESEARCH, JobType.ANALYZE_WALLETS}:
            raise ResearchError("RESEARCH_UNSUPPORTED_JOB")
        if summary.get(field) != json.loads(job.spec.canonical_payload):
            raise ResearchError("RESEARCH_JOB_RESULT_MISMATCH")
        # Only an exact manifest binding turns an operational candidate into a usable output.
        return result

    def resolve_prepare(self, start: int, stop: int) -> ResearchDatasetSpec:
        """Materialize the exact acquisition without reading the network in HTTP."""

        if self.network_id is None:
            raise ResearchError("RESEARCH_SOURCE_NOT_CONFIGURED")
        blocks = BlockRange(self.network_id, BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID, start, stop)
        # Materialize all installed semantic operands before submission or direct execution.
        return ResearchDatasetSpec(
            self.source_id, blocks, self.profile_digest, self.code_digest, self.runtime_digest
        )

    # Recipe defaults are resolved once here, identically for CLI and API callers.
    def resolve_analysis(
        self,
        snapshot_id: ArtifactId,
        *,
        # Shared defaults are canonicalized into the same immutable recipe for every caller.
        window_seconds: int = 60,
        minimum_shared_mints: int = 2,
        # An omitted selection includes all source-reported signers in the exact snapshot.
        wallets: tuple[str, ...] = (),
    ) -> WalletAnalysisSpec:
        """Authenticate the exact snapshot before the immutable command is queued."""

        summary = self.summary(snapshot_id)
        if summary["kind"] != "RESEARCH_SNAPSHOT":
            raise ResearchError("RESEARCH_EXPECTED_SNAPSHOT")
        # Historical observation bytes remain usable; execution requires current recipe code.
        return WalletAnalysisSpec(
            snapshot_id,
            self.code_digest,
            self.runtime_digest,
            # Semantic window, threshold and canonical selection determine the derived identity.
            window_seconds,
            minimum_shared_mints,
            tuple(sorted(set(wallets))),
        )

    def summary(self, artifact_id: ArtifactId) -> dict[str, object]:
        """Expose verified bounded metadata with no credentials or physical paths."""

        try:
            return self.store.summary(artifact_id)
        except ResearchError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            # Missing/corrupt bytes never expose local paths or library exception details.
            raise ResearchError("RESEARCH_ARTIFACT_UNAVAILABLE") from None

    def validate_command(self, payload: bytes, *, prepare: bool) -> None:
        """A generic submission must prove the same inputs as the typed research form."""

        document = json.loads(payload)
        if prepare:
            acquisition = dataset_spec(document)
            blocks = acquisition.block_range
            expected = self.resolve_prepare(blocks.from_block_ordinal, blocks.to_block_ordinal)
            # Source, network, recipe and runtime are controller-owned immutable operands.
            if acquisition != expected:
                raise ResearchError("RESEARCH_RERESOLVE_REQUIRED")
        else:
            analysis = analysis_spec(document)
            # Even a generic queue envelope must authenticate the selected snapshot first.
            expected_analysis = self.resolve_analysis(
                analysis.snapshot_id,
                window_seconds=analysis.window_seconds,
                minimum_shared_mints=analysis.minimum_shared_mints,
                # Validate complete signer selection together with the exact input manifest.
                wallets=analysis.wallets,
            )
            # A stale installed recipe may be reviewed, but cannot be silently executed.
            if analysis != expected_analysis:
                raise ResearchError("RESEARCH_RERESOLVE_REQUIRED")

    # Table reads have independent transport bounds, never a general analytical query surface.
    def page(
        self,
        artifact_id: ArtifactId,
        table: ResearchTable,
        # HTTP and CLI may choose only this finite table role, never a physical filename.
        *,
        after: int = -1,
        # Cursor and pair scope affect only this bounded read, not committed content.
        limit: int = 25,
        pair: int | None = None,
    ) -> tuple[dict[str, str], ...]:
        """Reject unbounded pagination before any file reader is opened."""

        integer(after, minimum=-1)
        integer(limit, minimum=1, maximum=MAX_PAGE_SIZE)
        if pair is not None:
            integer(pair)
        # Only validated read parameters may cross the columnar-store port.
        try:
            return self.store.page(artifact_id, table, after=after, limit=limit, pair=pair)
        except ResearchError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            # Typed transport errors remain safe even for malformed Parquet/footer bytes.
            raise ResearchError("RESEARCH_ARTIFACT_UNAVAILABLE") from None
