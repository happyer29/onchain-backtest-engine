"""Composition of the bounded observational research slice; no SQLite in children."""

import json
from pathlib import Path
from typing import cast

import clickhouse_connect

# Concrete source and analytical engines are selected only by the composition root.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.research.store import LocalResearchStore
from backtest.adapters.source.clickhouse.reader import ClickHouseClientProtocol
from backtest.adapters.source.clickhouse.research import ClickHouseResearchSource, profile_digest

# Core contracts are the only values passed through the concrete source/query implementations.
from backtest.application.models import CommittedArtifact, JobType
from backtest.application.ports.research import ResearchJobQuery

# Existing research contracts remain independent of bootstrap and native libraries.
from backtest.application.research import ResearchError, analysis_spec, dataset_spec
from backtest.application.use_cases.research import PrepareResearch, ResearchUseCases
from backtest.bootstrap.build_tools import BuildToolBundleRegistry
from backtest.bootstrap.config import Settings
from backtest.bootstrap.reference_bundles import ReferenceBundleDeclaration

# A source mapping supplies chain identity, not research completeness or replay admission.
from backtest.bootstrap.source import ConfiguredClickHouseSource
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest, NetworkId, SourceId
from backtest.runtime.runtime_lock import RuntimeManifest, build_runtime_manifest


def research_code_digest() -> ContentDigest:
    """Pin the complete recipe implementation without changing existing bundle roles."""

    sources = (
        "application/research.py",
        "application/ports/research.py",
        "application/use_cases/research.py",
        "adapters/source/clickhouse/research.py",
        # Both acquisition normalization and local query/layout bytes affect identity.
        "adapters/research/layout.py",
        "adapters/research/queries.py",
        "adapters/research/store.py",
        "bootstrap/research.py",
        # Core serialization and coordinate rules are transitive recipe dependencies.
        "domain/hashing.py",
        "domain/identifiers.py",
        "domain/time.py",
        "domain/chain.py",
    )
    # One canonical allowlist attests the recipe without registering it as an engine plugin.
    declaration = ReferenceBundleDeclaration.create(
        role="research:wallets",
        contract={"recipe": "wallet-co-buy-analysis/v2"},
        # The allowlist is canonical and never takes executable paths from a request.
        source_paths=tuple(sorted(sources)),
    )
    closure = BuildToolBundleRegistry(declarations=(declaration,)).snapshot()
    return ContentDigest(closure.manifest_for("research:wallets").bundle_id.hex)


def research_runtime_digest(manifest: RuntimeManifest) -> ContentDigest:
    """Retain installed runtime bytes; physical thread/env settings do not key this recipe."""

    fields = ("abi", "dependencies", "python", "operating_system")
    document = {name: manifest.document[name] for name in fields}
    return domain_digest("backtest.research-runtime/v1", document)


# Read-only controller composition and isolated child composition share installed identities.
def build_research_use_cases(
    settings: Settings,
    artifacts: LocalArtifactRepository,
    *,
    network_id: NetworkId | None = None,
    # Optional runtime reuse avoids rehashing the same installed environment at startup.
    runtime_manifest: RuntimeManifest | None = None,
    jobs: ResearchJobQuery | None = None,
) -> ResearchUseCases:
    """The controller can resolve and read artifacts without opening a source connection."""

    resources = settings.resources
    manifest = runtime_manifest or build_runtime_manifest(native_threads_per_process=1, environ={})
    store = LocalResearchStore(
        artifacts,
        memory_mb=min(512, resources.max_builder_memory_mb),
        # Research remains inside the existing admitted builder's disk and process budget.
        temporary_bytes=resources.max_run_tmp_gb * 1024**3,
        output_bytes=resources.max_run_output_gb * 1024**3,
        threads=1,
    )
    # These exact operands are materialized by the shared CLI/API resolver.
    return ResearchUseCases(
        store,
        research_code_digest(),
        research_runtime_digest(manifest),
        profile_digest(),
        # Network comes from local mappings; job-result lookup is controller-only.
        SourceId(settings.source.source_id),
        network_id,
        jobs,
    )


# The child creates only filesystem/source/query adapters, never a SQLite writer.
def execute_research_job(
    settings: Settings,
    job_type: JobType,
    payload: bytes,
    *,
    # The mapping is a deployment path; its endpoint and credentials never enter job identity.
    capabilities_file: Path | None = None,
) -> tuple[LocalArtifactRepository, CommittedArtifact]:
    """Resolve installed operands again inside the isolated, credential-scoped child."""

    artifacts = LocalArtifactRepository(
        settings.paths.data_root,
        staging_quota_bytes=settings.resources.tmp_quota_gb * 1024**3,
    )
    network = None
    # Analysis is a local-only consumer and must not construct a source mapping or client.
    if job_type is JobType.PREPARE_RESEARCH:
        from backtest.adapters.source.clickhouse import load_clickhouse_capabilities

        # A preparation cannot replace its pinned network with a display alias or endpoint.
        mapping = capabilities_file or settings.source.capabilities_file
        if mapping is None:
            raise ResearchError("RESEARCH_SOURCE_NOT_CONFIGURED")
        source = ConfiguredClickHouseSource(settings, load_clickhouse_capabilities(mapping))
        network, _ = source.chain_identity()
    # Recompute recipe/runtime digests inside the child before accepting the queued command.
    use_cases = build_research_use_cases(settings, artifacts, network_id=network)
    # Both typed and generic queue submissions pass this same current-identity check.
    use_cases.validate_command(payload, prepare=job_type is JobType.PREPARE_RESEARCH)
    if job_type is JobType.PREPARE_RESEARCH:
        result = _prepare(settings, use_cases, payload)
    elif job_type is JobType.ANALYZE_WALLETS:
        # DuckDB sees verified committed local observations only.
        result = use_cases.store.analyze(analysis_spec(json.loads(payload)))
    else:
        raise ResearchError("RESEARCH_UNSUPPORTED_JOB")
    return artifacts, result


def _prepare(settings: Settings, use_cases: ResearchUseCases, payload: bytes) -> CommittedArtifact:
    """Keep secret-bearing SDK exceptions and connection cleanup inside one redaction seam."""

    source = settings.source
    client = None
    result = None
    failure = "RESEARCH_SOURCE_FAILED"
    # Inspect and scan share one read-only connection; consistency is still UNKNOWN.
    try:
        client = clickhouse_connect.get_client(
            host=source.host,
            port=source.port,
            username=source.username,
            # Secret resolution occurs only in this source-enabled child connection scope.
            password=source.password(),
            database=source.database,
            secure=source.secure,
            verify=True,
        )
        # The reader receives no authority to choose arbitrary tables or statements.
        reader = ClickHouseResearchSource(
            cast(ClickHouseClientProtocol, client),
            database=source.database,
        )
        # Publication consumes the complete bounded stream and aborts if any source read fails.
        result = PrepareResearch(reader, use_cases.store).execute(dataset_spec(json.loads(payload)))
    except ResearchError as error:
        # Application error codes contain neither endpoint nor source-provided strings.
        failure = error.code
    except Exception:
        # Third-party exceptions can contain credentials; no original context may escape.
        failure = "RESEARCH_SOURCE_FAILED"
    finally:
        if client is not None:
            # Cleanup stays inside the same secret-redaction boundary as connection creation.
            try:
                client.close()
            except Exception:
                # A cleanup failure cannot turn a completed publication into partial output.
                if result is None:
                    failure = "RESEARCH_SOURCE_FAILED"
    if result is None:
        raise ResearchError(failure)
    return result
