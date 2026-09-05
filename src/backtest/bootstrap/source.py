"""Read-only remote source composition kept outside execution-only children."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import replace
from typing import Final, Protocol, cast

import clickhouse_connect

# Import clickhouse at the visible module dependency boundary.
from backtest.adapters.source.clickhouse import (
    ClickHouseCapability,
    ClickHouseClientProtocol,
    ClickHouseSourceReader,
    PumpfunIndexerV1Profile,
    registered_pumpfun_indexer_v1_profile,
)
from backtest.application.errors import ErrorCode, SourceEvidenceValidationError

# Import models at the visible module dependency boundary.
from backtest.application.models import (
    BoundedSourceEvidenceReceipt,
    BoundedSourceEvidenceRequest,
    CapabilityDescriptor,
    ExtractionRequest,
    QueryLimits,
    # Include source metadata so the models dependency remains explicit.
    SourceMetadata,
)
from backtest.application.ports.source import IndexedBatch
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
)
from backtest.bootstrap.config import Settings
from backtest.bootstrap.pumpfun_live_source import (
    PumpfunLiveSourceComposition,
    PumpfunLiveSourceError,
    PumpfunLiveSourceErrorCode,
)
from backtest.domain.identifiers import ContentDigest, NetworkId, PositionSchemaId, SourceId
from backtest.domain.time import BlockRange


# Keep the closable client contract and validation rules together.
class _ClosableClient(Protocol):
    def close(self) -> None: ...


_PUMPFUN_EVIDENCE_ERROR_CODES: Final[Mapping[PumpfunLiveSourceErrorCode, ErrorCode]] = {
    PumpfunLiveSourceErrorCode.PROFILE_INVALID: ErrorCode.PROFILE_INVALID,
    PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH: ErrorCode.REQUEST_IDENTITY_MISMATCH,
    PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED: ErrorCode.SOURCE_READ_FAILED,
    PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED: ErrorCode.NORMALIZATION_FAILED,
    PumpfunLiveSourceErrorCode.INCOMPLETE_BLOCK_RANGE: ErrorCode.INCOMPLETE_BLOCK_RANGE,
    PumpfunLiveSourceErrorCode.TRANSACTION_CLOCK_MISMATCH: (ErrorCode.TRANSACTION_CLOCK_MISMATCH),
    PumpfunLiveSourceErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH: (
        ErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH
    ),
    PumpfunLiveSourceErrorCode.CURVE_TRANSITION_MISMATCH: ErrorCode.CURVE_TRANSITION_MISMATCH,
    PumpfunLiveSourceErrorCode.LIFECYCLE_CONTRACT_MISMATCH: (ErrorCode.LIFECYCLE_CONTRACT_MISMATCH),
}


class ConfiguredClickHouseSource:
    """Local capability registry plus lazy, short-lived read-only connections."""

    def __init__(
        self,
        settings: Settings,
        capabilities: tuple[ClickHouseCapability, ...],
        *,
        pumpfun_live: PumpfunLiveSourceComposition | None = None,
        projector_digest: ContentDigest | None = None,
    ) -> None:
        # Execute the configured click house source init workflow in explicit, reviewable
        # steps.
        self._settings = settings
        self._source_id = SourceId(settings.source.source_id)
        self._capabilities = capabilities
        if pumpfun_live is None and projector_digest is not None:
            raise ValueError(
                "a projector digest cannot be bound without a Pump.fun live source composition"
            )
        if pumpfun_live is not None and pumpfun_live.raw_capabilities != capabilities:
            raise ValueError("Pump.fun live source composition uses another capability mapping")
        self._pumpfun_live = pumpfun_live
        self._projector_digest = projector_digest

    def list_capabilities(self, source_id: SourceId) -> tuple[CapabilityDescriptor, ...]:
        # Execute the configured click house source list capabilities workflow in
        # explicit, reviewable steps.
        self._require_source(source_id)
        if self._pumpfun_live is not None:
            return self._pumpfun_live.metadata_capabilities
        return tuple(item.descriptor for item in self._capabilities)

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        # Execute the configured click house source inspect metadata workflow in explicit,
        # reviewable steps.
        self._require_source(source_id)
        if not self._capabilities:
            raise RuntimeError("ClickHouse capability mapping is not configured")
        client: _ClosableClient | None = None
        metadata: SourceMetadata | None = None
        # Keep expected failures inside the configured click house source inspect metadata
        # error boundary.
        try:
            # Perform the protected configured click house source inspect metadata
            # operation before explicit failure handling.
            source = self._settings.source
            client = clickhouse_connect.get_client(
                host=source.host,
                port=source.port,
                username=source.username,
                # Keep the password and source password step visible while building
                # client.
                password=source.password(),
                database=source.database,
                secure=source.secure,
                verify=True,
            )
            # Assemble reader once so the configured click house source inspect metadata
            # workflow shares one value.
            reader = ClickHouseSourceReader(
                # The SDK stubs expose wider parameter types than the narrow
                # read-only protocol. Keep the cast at this third-party seam.
                client=cast(ClickHouseClientProtocol, client),
                source_id=self._source_id,
                capabilities=self._capabilities,
            )
            discovered = reader.inspect_metadata(source_id)
            if self._pumpfun_live is None:
                metadata = discovered
            else:
                metadata = replace(
                    discovered,
                    capabilities=self._pumpfun_live.metadata_capabilities,
                    capability_mapping_digest=self._pumpfun_live.capability_mapping_digest,
                    query_template_digest=self._pumpfun_live.query_template_digest,
                )
        # Translate exception through the configured click house source inspect metadata
        # boundary without hiding other errors.
        except Exception:
            # Driver failures may contain a URL. Do not retain their context.
            pass
        finally:
            # Handle the cleanup path after the protected configured click house source
            # inspect metadata operation.
            if client is not None:
                # Handle the configured click house source inspect metadata client is not
                # None branch as a distinct logical block.
                with suppress(Exception):
                    client.close()
        if metadata is None:
            raise RuntimeError("ClickHouse metadata connection failed")
        return metadata

    # Define configured click house source chain identity as one focused operation with an
    # explicit boundary.
    def chain_identity(self) -> tuple[NetworkId, PositionSchemaId]:
        """Return the exact immutable identity pinned by local mappings."""

        if not self._capabilities:
            raise RuntimeError("ClickHouse capability mapping is not configured")
        identities = {(item.network_id, item.position_schema_id) for item in self._capabilities}
        if len(identities) != 1:
            raise RuntimeError("ClickHouse capability mappings use mixed networks")
        # Return the completed configured click house source chain identity result without
        # a hidden fallback.
        return next(iter(identities))

    def inspect_bounded_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        """Open one short-lived connection for bounded validation queries."""

        self._require_source(request.source_id)
        client: _ClosableClient | None = None
        receipts: tuple[BoundedSourceEvidenceReceipt, ...] | None = None
        evidence_error_code: ErrorCode | None = None
        try:
            # Perform the protected configured click house source inspect bounded evidence
            # operation before explicit failure handling.
            source = self._settings.source
            client = clickhouse_connect.get_client(
                host=source.host,
                port=source.port,
                username=source.username,
                # Keep the password and source password step visible while building
                # client.
                password=source.password(),
                database=source.database,
                secure=source.secure,
                verify=True,
            )
            # Assemble reader once so the configured click house source inspect bounded
            # evidence workflow shares one value.
            reader = ClickHouseSourceReader(
                client=cast(ClickHouseClientProtocol, client),
                source_id=self._source_id,
                capabilities=self._capabilities,
            )
            # Assemble receipts once so the configured click house source inspect bounded
            # evidence workflow shares one value.
            if self._pumpfun_live is None:
                receipts = reader.inspect_bounded_evidence(request)
            else:
                projector_digest = self._projector_digest
                if projector_digest is None:  # established by __init__
                    raise RuntimeError("Pump.fun projector digest is not configured")
                receipts = self._pumpfun_live.inspect_bounded_evidence(
                    reader,
                    request,
                    projector_digest=projector_digest,
                )
        except PumpfunLiveSourceError as error:
            evidence_error_code = _PUMPFUN_EVIDENCE_ERROR_CODES.get(error.code)
        except Exception:
            pass
        finally:
            # Handle the cleanup path after the protected configured click house source
            # inspect bounded evidence operation.
            if client is not None:
                # Handle the configured click house source inspect bounded evidence client
                # is not None branch as a distinct logical block.
                with suppress(Exception):
                    client.close()
        if evidence_error_code is not None:
            raise SourceEvidenceValidationError(evidence_error_code)
        if receipts is None:
            raise RuntimeError("bounded ClickHouse evidence inspection failed")
        return receipts

    # Define configured click house source scan as one focused operation with an explicit
    # boundary.
    def scan(self, request: ExtractionRequest) -> Iterator[IndexedBatch]:
        """Open one short-lived read-only connection for one bounded shard."""

        client: _ClosableClient | None = None
        failure = False
        try:
            # Perform the protected configured click house source scan operation before
            # explicit failure handling.
            source = self._settings.source
            client = clickhouse_connect.get_client(
                host=source.host,
                port=source.port,
                username=source.username,
                # Keep the password and source password step visible while building
                # client.
                password=source.password(),
                database=source.database,
                secure=source.secure,
                verify=True,
            )
            # Assemble reader once so the configured click house source scan workflow
            # shares one value.
            reader = ClickHouseSourceReader(
                client=cast(ClickHouseClientProtocol, client),
                source_id=self._source_id,
                capabilities=self._capabilities,
            )
            # Keep the yield step explicit within the configured click house source scan
            # workflow.
            if self._pumpfun_live is None:
                yield from reader.scan(request)
            else:
                yield from self._pumpfun_live.scan(reader, request)
        except Exception:
            failure = True
        finally:
            # Handle the cleanup path after the protected configured click house source
            # scan operation.
            if client is not None:
                # Handle the configured click house source scan client is not None branch
                # as a distinct logical block.
                with suppress(Exception):
                    client.close()
        if failure:
            raise RuntimeError("bounded ClickHouse extraction failed") from None

    def _require_source(self, source_id: SourceId) -> None:
        # Execute the configured click house source require source workflow in explicit,
        # reviewable steps.
        if source_id != self._source_id:
            raise ValueError(f"unknown source {source_id}")

    def build_evidence_request(
        self,
        *,
        source_id: SourceId,
        block_range: BlockRange,
        decision_range: BlockRange,
        query_limits: QueryLimits,
    ) -> BoundedSourceEvidenceRequest:
        """Bind a bounded proof request to the installed live source semantics."""

        self._require_source(source_id)
        composition = self._pumpfun_live
        projector_digest = self._projector_digest
        if composition is None or projector_digest is None:
            raise ValueError("bounded Pump.fun evidence requires the installed live source profile")
        return BoundedSourceEvidenceRequest(
            source_id=source_id,
            block_range=block_range,
            decision_range=decision_range,
            capability_mapping_digest=composition.capability_mapping_digest,
            query_template_digest=composition.query_template_digest,
            projector_digest=projector_digest,
            normalizer_digest=composition.normalizer_digest,
            launch_universe_policy_id=PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
            skipped_slot_sentinel_policy_id=SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
            terminal_lifecycle_ordering_policy_id=(PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID),
            query_limits=query_limits,
        )


def select_clickhouse_query_profile(
    capabilities: tuple[ClickHouseCapability, ...],
) -> PumpfunIndexerV1Profile | None:
    """Resolve only installed, fixed source profiles at the composition boundary.

    A returned profile is not itself source evidence and does not promote any
    fidelity.  The dedicated Pump normalizer/evaluator must be wired before the
    profile can replace the generic direct-column reader path.
    """

    return registered_pumpfun_indexer_v1_profile(capabilities)


__all__ = ["ConfiguredClickHouseSource", "select_clickhouse_query_profile"]
