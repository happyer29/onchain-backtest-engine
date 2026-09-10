"""Exact artifact-bound copy draft resolution with no source access during replay."""

from contextlib import AbstractContextManager, nullcontext
from typing import cast

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.adapters.columnar.arrow import CanonicalParquetReplaySource
from backtest.adapters.columnar.numpy import NumpyMmapReplaySource

# Resolver accepts only committed manifests and the installed versioned component closure.
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.copy_run_contract import copy_component_configs, require_copy_preparation
from backtest.application.ports.sniping_runs import SnipingHistoricalEventSource
from backtest.application.run_drafts import PumpfunCopyBuyRunDraft
from backtest.application.run_specs import (
    # Resolution materializes both semantic components and the chosen verified physical input.
    AssetBalance,
    ReplayContract,
    ReplayInputFormat,
    ResolvedComponent,
    ResolvedReplayInput,
    # Only the immutable resolved envelope may enter preflight or the durable queue.
    ResolvedRunSpec,
)

# Shared native quote identity and build tools retain their authoritative verification rules.
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_QUOTE_ASSET_ID
from backtest.bootstrap.copy_bundles import PumpfunCopyBuyBundleRegistry
from backtest.bootstrap.sniping_run_resolver import _unit_sniping_resolver_tools
from backtest.domain.chain import (
    # The full genesis identity prevents alias-based cross-network artifact reuse.
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.identifiers import BundleId, RuntimeLockId


class CopyRunResolutionError(RuntimeError):
    """A draft, installed bundle or exact local input cannot satisfy copy-buy v1."""


class PumpfunCopyBuyRunSpecResolver:
    """Resolve one closed reference strategy without accepting aliases or signerless history."""

    def __init__(
        self,
        artifacts: LocalArtifactRepository,
        runtime_lock_id: RuntimeLockId,
        *,
        # Reader memory and thread bounds remain operational rather than strategy identity.
        parquet_memory_limit_mb: int,
        threads: int,
        # Pinned build tools verify canonical and derived input bytes transitively.
        expected_projector_bundle_id: BundleId | None = None,
        build_tools: PinnedCodeBundleSet | None = None,
        registry: PumpfunCopyBuyBundleRegistry | None = None,
    ) -> None:
        # Reject invalid reader limits before constructing any analytical reader.
        if parquet_memory_limit_mb <= 0 or threads <= 0:
            raise ValueError("copy resolver reader limits must be positive")
        self._artifacts, self._runtime_lock = artifacts, runtime_lock_id
        self._memory, self._threads = parquet_memory_limit_mb, threads
        # Production wiring always supplies current exact tool identities.
        self._projector = expected_projector_bundle_id
        self._tools = build_tools or _unit_sniping_resolver_tools()
        self._registry = registry or PumpfunCopyBuyBundleRegistry()

    def resolve(self, draft: PumpfunCopyBuyRunDraft) -> ResolvedRunSpec:
        """Verify source coverage, source bytes and component configs before returning a spec."""
        if not isinstance(draft, PumpfunCopyBuyRunDraft):
            raise TypeError("copy resolver requires a PumpfunCopyBuyRunDraft")
        try:
            return self._resolve(draft)
        except (RuntimeError, TypeError, ValueError) as error:
            # Public failure stays bounded and carries no paths, SQL or credential-bearing text.
            raise CopyRunResolutionError(
                "copy exact artifact/config closure failed verification"
            ) from error

    def _resolve(self, draft: PumpfunCopyBuyRunDraft) -> ResolvedRunSpec:
        """A readable snapshot/ReplayPack cannot substitute matching ID strings for manifests."""
        closure = self._registry.snapshot()
        configs = copy_component_configs(draft)
        components = tuple(
            ResolvedComponent.create(
                role=item.role,
                # Each installed manifest contributes its exact bundle and API version.
                bundle_id=item.bundle_id,
                api_version=item.api_version,
                # Materialized component configs include every fixed and user-selectable operand.
                config=configs[item.role],
            )
            for item in closure.manifests
        )
        # Canonical input is verified directly when no derived ReplayPack is requested.
        if draft.replay_pack_id is None:
            reader = CanonicalParquetReplaySource(
                self._artifacts,
                draft.snapshot_id,
                duckdb_memory_limit_mb=self._memory,
                # Keep resource limits outside semantic hashes while verifying the exact projector.
                threads=self._threads,
                expected_projector_bundle_id=self._projector,
                build_tools=self._tools,
            )
            context: AbstractContextManager[SnipingHistoricalEventSource] = nullcontext(reader)
        # Only the optional physical derived path changes; snapshot identity remains fixed.
        else:
            # The derived reader verifies its snapshot and exact build dependency closure.
            context = cast(
                AbstractContextManager[SnipingHistoricalEventSource],
                NumpyMmapReplaySource(
                    self._artifacts,
                    draft.replay_pack_id,
                    # The mmap reader must verify every pinned build input before yielding events.
                    build_tools=self._tools,
                ),
            )
        with context as source:
            replay_input = ResolvedReplayInput(ReplayInputFormat.CANONICAL_PARQUET)
            # A matching pack ID string cannot stand in for its verified parent snapshot.
            if draft.replay_pack_id is not None:
                pack = cast(NumpyMmapReplaySource, source)
                if pack.snapshot_id != draft.snapshot_id:
                    raise ValueError("copy ReplayPack derives from a different snapshot")
                # Layout remains a checked derived input, not canonical source identity.
                replay_input = ResolvedReplayInput(
                    ReplayInputFormat.REPLAY_PACK,
                    replay_layout_schema_id=pack.replay_layout_schema_id,
                    replay_pack_id=draft.replay_pack_id,
                )
            # Both physical readers must prove the same dataset revision from committed manifests.
            if source.dataset_revision_id != draft.dataset_revision_id:
                raise ValueError("copy dataset revision differs from the verified input")
            # Integer coordinates are meaningful only for the exact immutable network/schema.
            if (
                source.network_id != SOLANA_MAINNET_NETWORK_ID
                or source.position_schema_id != BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
            ):
                raise ValueError("copy v1 requires the exact Solana block32 transaction contract")
            # A reader cannot redefine the decision interval already pinned by preparation.
            if source.decision_range != source.dataset_spec.decision_range:
                raise ValueError("copy source decision range differs from its manifest")
            require_copy_preparation(source.dataset_spec, draft.signing_wallets, draft.policy)
            clock = source.transaction_clock()
            # Clock and canonical events cannot belong to different chains or position schemas.
            if (
                clock.network_id != source.network_id
                or clock.position_schema_id != source.position_schema_id
            ):
                raise ValueError("copy clock identity differs from verified events")
            # Only verified identities are copied into the immutable execution envelope.
            spec = ResolvedRunSpec.create(
                network_id=source.network_id,
                position_schema_id=source.position_schema_id,
                dataset_revision_id=source.dataset_revision_id,
                logical_content_hash=source.logical_content_hash,
                # Snapshot and replay semantics remain separate identity operands.
                snapshot_id=draft.snapshot_id,
                replay_semantics_id=source.replay_semantics_id,
                # Configs, runtime and the exact input closure are resolved before admission.
                replay_input=replay_input,
                components=components,
                runtime_lock_id=self._runtime_lock,
                initial_portfolio=(
                    AssetBalance(
                        # The initial balance carries its native asset tag, independent of
                        # network-fee defaults.
                        PUMPFUN_SNIPING_QUOTE_ASSET_ID,
                        draft.initial_sol_balance_lamports,
                    ),
                ),
                # Seed and exact replay contract remain semantic inputs across physical formats.
                root_seed=draft.root_seed,
                replay_contract=ReplayContract.CANONICAL_EXACT,
                # Independent runs can share semantics even when physical input layout differs.
            )
        closure.require_components(spec.components, spec.dependency_merkle_root)
        return spec
