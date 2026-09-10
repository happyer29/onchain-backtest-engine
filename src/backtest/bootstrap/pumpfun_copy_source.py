"""Bind independent leader enumeration to complete, bounded all-signer Pump histories."""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime

# Remote access stays inside the fixed, bounded ClickHouse adapter.
from backtest.adapters.source.clickhouse.pumpfun_copybuy import PumpfunCopyBuyQueryProfile
from backtest.adapters.source.clickhouse.pumpfun_indexer_v1 import (
    PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE,
)
from backtest.adapters.source.clickhouse.query import ClickHouseCapability, ClickHouseQueryPolicy

# Streaming batches carry explicit columns and query identity into normalization.
from backtest.adapters.source.clickhouse.reader import ClickHouseSourceReader
from backtest.adapters.source.common import SourceAdapterError, SourceBatch

# Bootstrap alone connects the source adapter, pure transforms and application contracts.
from backtest.application.code_bundles import PinnedCodeBundleSet
from backtest.application.copy_source import CopyBuyCoverageEvidence, CopySourceSelection
from backtest.application.models import (
    COPYBUY_SOURCE_EVIDENCE_SCHEMA,
    BoundedSourceEvidenceReceipt,
    # Evidence requests and extraction shards use separate typed application contracts.
    BoundedSourceEvidenceRequest,
    CapabilityCutEvidence,
    CapabilityStream,
    ExtractionRequest,
    build_bounded_source_evidence_receipt,
    # Indexed rows remain bounded batches rather than a mirrored remote table.
)
from backtest.application.ports.source import IndexedBatch

# Mathematical source proofs are shared; copy enumeration and coverage stay separate.
from backtest.application.source_evidence import (
    SkippedSlotSentinelEvidence,
    TerminalLifecycleOrderingEvidence,
)
from backtest.bootstrap.pumpfun_live_source import (
    # Reuse the exact fixed source validators, not a weaker parallel implementation.
    _STREAM_ORDER,
    PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS,
    PumpfunLiveSourceComposition,
    PumpfunLiveSourceErrorCode,
    _EvidenceAccumulator,
    # Shared validation failures retain bounded error codes without driver diagnostics.
    _fail,
    _normalized_descriptor,
    _projection_capability,
    _proven_proofs,
    _proven_source_fidelity,
    # Raw batch checks and deterministic shard boundaries precede every transformation.
    _raise_normalization,
    _shards,
    _validate_raw_batch,
    build_pumpfun_live_source_composition,
)

# Only completed source checks may produce explicit finality and consistency evidence.
from backtest.domain.fidelity import ChainFinality, IngestionCompleteness, SourceConsistency
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import ContentDigest

# Projection retains original source occurrence IDs while adding immutable actor bytes.
from backtest.domain.market_events import EventKindName
from backtest.plugins.protocols.pumpfun.copybuy_coverage import CopySignalCoverage
from backtest.plugins.protocols.pumpfun.copybuy_normalizer import PumpfunCopyBuyLiveNormalizer
from backtest.plugins.protocols.pumpfun.copybuy_payload import COPYBUY_TRADE_PAYLOAD_SCHEMA
from backtest.plugins.protocols.pumpfun.live_normalizer import (
    # Clock sentinels and terminal lifecycle normalization retain their pinned profiles.
    PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
    PumpfunLiveNormalizationError,
    _block_time,
    _OrderedDigest,
    # Source occurrence keys use validated original signatures and public keys.
    _public_key,
    _signature,
)

# The projection family is fixed in this composition and cannot be changed by source rows.
from backtest.plugins.protocols.pumpfun.projector import (
    PumpfunProjectionSpec,
    PumpfunProtocolProjector,
)
from backtest.plugins.protocols.pumpfun.sniping import (
    # Launch and lifecycle payloads retain their existing meanings beside copy trade payloads.
    PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
    PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
)

_MAXIMUM_CANDIDATES = 100_000


@dataclass(frozen=True, slots=True)
class PumpfunCopySourceComposition(PumpfunLiveSourceComposition):
    """An independent source family using the same read-only connection boundary."""

    selection: CopySourceSelection
    copy_profile: PumpfunCopyBuyQueryProfile
    projector: PumpfunProtocolProjector

    def scan(
        self, reader: ClickHouseSourceReader, request: ExtractionRequest
    ) -> Iterator[IndexedBatch]:
        """Extract only the exact selected history using fresh, bounded fixed queries."""
        capability = self._raw_capability(request.shard.capability_id)
        descriptor = self._metadata_descriptor(request.shard.capability_id)
        # Validate requested normalized columns against the exact inspected descriptor.
        if (
            request.shard.columns != descriptor.columns
            or request.decision_range != self.selection.decision_range
        ):
            # A mismatched extraction command cannot open a source read.
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
        # Empty shards are normalized and validated through the same streaming contract.
        stream, cut = descriptor.stream, request.shard.block_range
        query = self.copy_profile.build_query(
            stream=stream, database=capability.database, block_range=cut, policy=self.query_policy
        )
        session = self.normalizer.begin(
            # Each shard gets fresh normalization state while preserving its explicit covered range.
            stream=stream,
            capability_id=descriptor.capability_id,
            covered_range=cut,
        )
        # Track an empty shard explicitly so finishing cannot skip its normalizer checks.
        seen = False
        try:
            for batch in reader.scan_pumpfun_copybuy(request, query, self.selection):
                # Reader reconstruction proves query identity; normalization proves each row.
                _validate_raw_batch(
                    batch,
                    capability_id=descriptor.capability_id,
                    covered_range=cut,
                    columns=self.normalizer.raw_columns(stream),
                    # Query fingerprints bind the returned batch to the exact bounded request.
                    query_fingerprint=query.fingerprint,
                )
                seen = True
                yield session.normalize(batch)
            if not seen:
                # An empty read still exercises the normalizer and final shard checks.
                yield session.normalize(
                    SourceBatch(
                        descriptor.capability_id,
                        cut,
                        self.normalizer.raw_columns(stream),
                        # Empty rows preserve columns and provenance without fabricating a canonical
                        # event.
                        (),
                        query.fingerprint,
                    )
                )
            session.finish()
        # Normalization failures and source transport failures remain distinct typed errors.
        except PumpfunLiveNormalizationError as error:
            _raise_normalization(error)
        except SourceAdapterError:
            _fail(PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED)

    def inspect_bounded_evidence(
        self,
        reader: ClickHouseSourceReader,
        request: BoundedSourceEvidenceRequest,
        *,
        # Projector identity is an explicit operand of bounded source proof.
        projector_digest: ContentDigest,
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        """Reconcile candidates, creation and every transition before constructing receipts."""
        self._validate_evidence_request(request, projector_digest)
        if (
            request.copy_selection != self.selection
            or projector_digest != self.projector.config_digest
        ):
            # Reject a changed wallet set or projector before independent enumeration starts.
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
        evidence = _EvidenceAccumulator(request)
        coverage = _CopyCoverageAccumulator(self.selection)
        try:
            # Candidate enumeration runs first without any creation JOIN or Mayhem filter.
            self._read_candidates(reader, request, coverage)
            for stream in _STREAM_ORDER:
                self._read_stream(reader, request, stream, evidence, coverage)
            evidence.finish()
            proof = coverage.finish()
        # A failed proof never creates a receipt or upgrades static UNKNOWN capabilities.
        except PumpfunLiveNormalizationError as error:
            _raise_normalization(error)
        except SourceAdapterError:
            _fail(PumpfunLiveSourceErrorCode.SOURCE_READ_FAILED)
        # Malformed rows or inconsistent independent reads abort the whole source cut.
        except (TypeError, ValueError, OverflowError):
            _fail(PumpfunLiveSourceErrorCode.NORMALIZATION_FAILED)
        return self._copy_receipts(request, evidence, proof)

    def _validate_evidence_request(
        self, request: BoundedSourceEvidenceRequest, projector_digest: ContentDigest
    ) -> None:
        """Use the base identity checks with this explicitly versioned classification policy."""
        if request.launch_universe_policy_id != self.normalizer.launch_universe_policy_id:
            _fail(PumpfunLiveSourceErrorCode.REQUEST_IDENTITY_MISMATCH)
        # Shared identity checks are policy-aware and retain all mapping/network operands.
        super(PumpfunCopySourceComposition, self)._validate_evidence_request(
            request, projector_digest
        )

    def _read_candidates(
        self,
        reader: ClickHouseSourceReader,
        request: BoundedSourceEvidenceRequest,
        coverage: "_CopyCoverageAccumulator",
        # The accumulator retains only bounded occurrence digests for reconciliation.
    ) -> None:
        """Independent candidate queries use the actual decision range, never the lookback."""
        capability = self._raw_capability_for_stream(CapabilityStream.PUMP_CURVE_TRADE)
        # Candidate enumeration obeys the same configured per-query cap as market history.
        span = min(PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS, self.query_policy.evidence_max_block_span)
        for cut in _shards(self.selection.decision_range, maximum_span=span):
            # Each candidate shard is independently fingerprinted before streaming its rows.
            query = self.copy_profile.build_candidates(
                database=capability.database, block_range=cut, policy=self.query_policy
            )
            coverage.queries.add(query.fingerprint)
            # A bounded fingerprint remains recorded even when a shard contains no purchases.
            for batch in reader.stream_pumpfun_copybuy_evidence(
                request,
                selection=self.selection,
                capability_id=capability.descriptor.capability_id,
                block_range=cut,
                # Candidate enumeration is a separate fixed query without creation filtering.
                query=query,
                candidates=True,
            ):
                coverage.add_candidates(batch)

    def _read_stream(
        self,
        reader: ClickHouseSourceReader,
        request: BoundedSourceEvidenceRequest,
        stream: CapabilityStream,
        # State-transition evidence and signer coverage are accumulated independently.
        evidence: _EvidenceAccumulator,
        coverage: "_CopyCoverageAccumulator",
    ) -> None:
        """Full market streams include every trader from creation through the settlement tail."""
        capability = self._raw_capability_for_stream(stream)
        selected = (
            self.selection.history_range
            if stream is CapabilityStream.TOKEN_LAUNCH
            else request.block_range
            # Launch targets stop at the decision end; market state continues through settlement.
        )
        span = min(PUMPFUN_LIVE_EVIDENCE_SHARD_BLOCKS, self.query_policy.evidence_max_block_span)
        for cut in _shards(selected, maximum_span=span):
            query = self.copy_profile.build_query(
                stream=stream,
                # The configured query cap can only shorten a shard, never widen the declared cut.
                database=capability.database,
                block_range=cut,
                policy=self.query_policy,
            )
            # Normalizer observations retain skipped-slot, Mayhem and terminal-order provenance.
            session = self.normalizer.begin(
                stream=stream,
                capability_id=capability.descriptor.capability_id,
                covered_range=cut,
                observation_sink=evidence.observe,
                # Observation evidence is collected during normalization, before proof construction.
            )
            for raw in reader.stream_pumpfun_copybuy_evidence(
                request,
                selection=self.selection,
                capability_id=capability.descriptor.capability_id,
                # Every streamed shard remains inside its declared typed block interval.
                block_range=cut,
                query=query,
            ):
                _validate_raw_batch(
                    raw,
                    # Check raw columns and provenance before interpreting source values.
                    capability_id=capability.descriptor.capability_id,
                    covered_range=cut,
                    columns=self.normalizer.raw_columns(stream),
                    query_fingerprint=query.fingerprint,
                )
                # Normalized rows must reconcile both shared curve state and independent copy
                # coverage.
                normalized = session.normalize(raw)
                # Run exact state/clock checks before accepting rows into copy coverage.
                evidence.consume(stream, raw, normalized)
                coverage.consume(stream, raw, normalized, self.projector)
            evidence.add_summary(stream, cut, query.fingerprint, session.finish())

    def _copy_receipts(
        self,
        request: BoundedSourceEvidenceRequest,
        evidence: _EvidenceAccumulator,
        coverage: CopyBuyCoverageEvidence,
        # Receipts are constructed only from successfully finalized evidence accumulators.
    ) -> tuple[BoundedSourceEvidenceReceipt, ...]:
        """The new result identity binds shared proof outcomes and independent copy coverage."""
        shared = evidence.result_digest(
            capability_mapping_digest=self.capability_mapping_digest,
            query_template_digest=self.query_template_digest,
            normalizer_digest=self.normalizer_digest,
            projector_digest=self.projector.config_digest,
            # The copy result additionally binds independent candidate coverage to shared proofs.
        )
        digest = domain_digest(
            "backtest.pumpfun-copy-source-result.v1",
            {"shared_result_digest": shared.hex, "coverage": coverage.identity_document()},
        )
        # Queries from candidate enumeration are retained alongside all market-stream queries.
        queries = tuple(
            sorted(
                evidence.query_fingerprints | set(coverage.candidate_query_fingerprints),
                key=lambda item: item.hex,
            )
            # The sorted query set is shared by all capability receipts.
        )
        # All four receipts share one cut revision and one reconciled candidate proof.
        receipts = []
        for stream in _STREAM_ORDER:
            descriptor = self._metadata_descriptor_for_stream(stream)
            cut = CapabilityCutEvidence(
                capability_id=descriptor.capability_id,
                # Every capability receipt names the same closed source cut and watermark.
                block_range=request.block_range,
                snapshot_cut_to_block=request.block_range.to_block_ordinal,
                chain_finality=ChainFinality.FINALIZED,
                ingestion_watermark_to_block=request.block_range.to_block_ordinal,
                # Complete source consistency comes from the evaluated cross-stream checks.
                completeness=IngestionCompleteness.COMPLETE_TO_WATERMARK,
                consistency=SourceConsistency.SNAPSHOT_CONSISTENT,
                upstream_revision=f"pumpfun-copy-cut-v1:{digest.hex}",
            )
            # One authoritative receipt is emitted per required capability stream.
            receipts.append(
                build_bounded_source_evidence_receipt(
                    source_id=request.source_id,
                    capability_id=descriptor.capability_id,
                    protocol_version=descriptor.protocol_version,
                    # Capability protocol and schema versions participate in the immutable receipt.
                    capability_schema_version=descriptor.schema_version,
                    capability_mapping_digest=self.capability_mapping_digest,
                    # Configuration, query and projector operands are exact and secret-free.
                    query_template_digest=self.query_template_digest,
                    projector_digest=self.projector.config_digest,
                    normalizer_digest=self.normalizer_digest,
                    cut_evidence=cut,
                    decision_range=request.decision_range,
                    # Proof flags describe checks that have already completed for this exact cut.
                    proofs=_proven_proofs(stream),
                    source_fidelity=_proven_source_fidelity(stream),
                    query_fingerprints=queries,
                    result_digest=digest,
                    observed_rows=evidence.raw_rows[stream],
                    # Copy coverage and its schema version prevent reuse as signerless Sniping
                    # evidence.
                    copy_coverage=coverage,
                    schema=COPYBUY_SOURCE_EVIDENCE_SCHEMA,
                    # Stream-local proof placement remains explicit and validated by planning.
                    skipped_slot_sentinel=(
                        SkippedSlotSentinelEvidence(
                            SOLANA_SKIPPED_SLOT_SENTINEL_PROFILE_ID,
                            evidence.sentinel_count,
                            evidence.sentinel_digest,
                            # Only the clock receipt carries skipped-slot sentinel evidence.
                        )
                        if stream is CapabilityStream.BLOCK_CLOCK
                        else None
                    ),
                    # Atomic terminal ordering belongs exclusively to the lifecycle capability.
                    terminal_lifecycle_ordering=(
                        TerminalLifecycleOrderingEvidence(
                            PUMPFUN_TERMINAL_LIFECYCLE_PROFILE_ID,
                            evidence.derived_lifecycle_count,
                            evidence.lifecycle_digest,
                            # Derived lifecycle events retain their ordered digest and count.
                        )
                        if stream is CapabilityStream.PUMP_CURVE_LIFECYCLE
                        else None
                        # Other capability receipts must not duplicate authoritative lifecycle
                        # evidence.
                    ),
                )
            )
        # Canonical capability ordering makes receipt tuples independent of traversal order.
        return tuple(sorted(receipts, key=lambda receipt: receipt.capability_id.value))


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Keep a bounded digest, not the full source row, for independent read reconciliation."""

    mint: str
    digest: ContentDigest
    block: int
    transaction: int
    instruction: int


class _CopyCoverageAccumulator:
    """No missing initial state or eligible purchase can be hidden by a source JOIN."""

    def __init__(self, selection: CopySourceSelection) -> None:
        self.selection = selection
        self.candidates: dict[tuple[str, int], _Candidate] = {}
        self.creations: dict[str, int] = {}
        self.seen: set[tuple[str, int]] = set()
        # Operational caps bound the retained candidate universe without silently filtering it.
        self.queries: set[ContentDigest] = set()
        self.columns: tuple[str, ...] = ()
        self.signals = CopySignalCoverage(selection, maximum_mints=_MAXIMUM_CANDIDATES)

    def add_candidates(self, batch: IndexedBatch) -> None:
        """Successful duplicate collapse is accepted only with the raw variant proof."""
        if self.columns and self.columns != batch.columns:
            raise ValueError("candidate query columns changed")
        self.columns = batch.columns
        for row in batch.rows:
            values = dict(zip(batch.columns, row, strict=True))
            # Exact signer membership and success are verified independently of SQL predicates.
            _require_candidate(values, self.selection)
            key = (_signature(values["signature"]), _number(values["raw_instruction_index"]))
            if key in self.candidates or len(self.candidates) >= _MAXIMUM_CANDIDATES:
                raise ValueError("duplicate or excessive copy candidates")
            self.candidates[key] = _Candidate(
                # Store a compact digest and coordinates instead of retaining each full candidate
                # row.
                _public_key(values["mint"]),
                _row_digest(values, self.columns),
                _number(values["block_ordinal"]),
                _number(values["transaction_index"]),
                key[1],
                # Original instruction identity preserves separate buys within one transaction.
            )

    def consume(
        self,
        stream: CapabilityStream,
        raw: IndexedBatch,
        normalized: IndexedBatch,
        # The projector emits actor-bearing canonical events for independent signal hashing.
        projector: PumpfunProtocolProjector,
    ) -> None:
        """Creation classification precedes all-signer transitions and eligible signal hashing."""
        if stream is CapabilityStream.TOKEN_LAUNCH:
            for row in raw.rows:
                values = dict(zip(raw.columns, row, strict=True))
                mint, mode = _public_key(values["mint"]), _number(values["mayhem_mode"])
                if mint in self.creations or mode not in (0, 1):
                    # A duplicate creation or unknown Mayhem mode cannot silently narrow the
                    # universe.
                    raise ValueError("copy creation is ambiguous")
                self.creations[mint] = mode
        # Market normalization already checks fees, mode and positive-input dust transitions.
        if stream is not CapabilityStream.PUMP_CURVE_TRADE:
            return
        for row in raw.rows:
            values = dict(zip(raw.columns, row, strict=True))
            key = (_signature(values["signature"]), _number(values["raw_instruction_index"]))
            # Only independently enumerated leader occurrences need candidate reconciliation.
            candidate = self.candidates.get(key)
            # Compare every raw candidate field, including multiplicity and reserve amounts.
            if candidate is not None:
                if key in self.seen or candidate.digest != _row_digest(values, self.columns):
                    raise ValueError("candidate differs from all-signer history")
                self.seen.add(key)
        # Canonical signal coverage is recomputed after raw occurrence equality is proven.
        for event in projector.project(normalized):
            self.signals.consume(event)

    def finish(self) -> CopyBuyCoverageEvidence:
        """Known Mayhem is excluded explicitly; a missing creation rejects the entire cut."""
        mints = {candidate.mint for candidate in self.candidates.values()}
        if mints != self.creations.keys():
            raise ValueError("copy candidates have missing or extra creations")
        # Eligibility is determined only by immutable creation-time mode.
        eligible = {
            key
            for key, value in self.candidates.items()
            if self.creations[value.mint] == 0
            # Known Mayhem is removed explicitly; every eligible occurrence must still be present.
        }
        if eligible != self.seen or self.signals.count != len(eligible):
            raise ValueError("copy candidate occurrence coverage is incomplete")
        # Exclusions retain original occurrence identity in deterministic source order.
        exclusions = _OrderedDigest(
            "backtest.pumpfun-copy-exclusions.v1", self.selection.document()
        )
        for key, value in self.candidates.items():
            if self.creations[value.mint] == 1:
                # Exclusion evidence retains source occurrence coordinates, never runtime orders.
                exclusions.update(
                    {
                        "signature": key[0],
                        "instruction": value.instruction,
                        "block": value.block,
                        # Transaction and mint distinguish exclusions that share a signature or
                        # block.
                        "transaction": value.transaction,
                        "mint": value.mint,
                        "reason": "MAYHEM_EXCLUDED",
                    }
                )
        # Mint coverage and occurrence coverage are separate completeness obligations.
        eligible_mints = sum(mode == 0 for mode in self.creations.values())
        if eligible_mints != self.signals.mint_count:
            raise ValueError("copy candidate mint coverage is incomplete")
        return CopyBuyCoverageEvidence(
            self.selection,
            # The receipt exposes classified, eligible and excluded occurrence counts.
            len(self.candidates),
            len(eligible),
            len(self.candidates) - len(eligible),
            len(mints),
            eligible_mints,
            # Mint counts separately prove that initialization covered the entire candidate
            # universe.
            len(mints) - eligible_mints,
            # Signal bytes are recomputed from committed canonical rows before root publication.
            self.signals.digest,
            exclusions.digest(),
            tuple(sorted(self.queries, key=lambda item: item.hex)),
        )


def _require_candidate(values: dict[str, object], selection: CopySourceSelection) -> None:
    """A fixed SQL template is not a substitute for validating returned candidate rows."""
    signer = _public_key(values["signing_wallet"])
    if signer not in {wallet.value for wallet in selection.signing_wallets}:
        raise ValueError("candidate signer is outside selection")
    if _text(values["direction"]) != "buy" or _number(values["failed"]) != 0:
        raise ValueError("candidate is not a successful buy")
    # Only the explicitly mapped SOL quote is admitted for copy execution.
    if _text(values["quote_asset"]) != PUMPFUN_INDEXER_V1_WRAPPED_SOL_QUOTE:
        raise ValueError("copy candidate is not SOL paired")
    # Source deduplication must preserve multiplicity and prove only one payload variant.
    if _number(values["payload_variant_count"]) != 1 or _number(values["source_row_count"]) < 1:
        raise ValueError("candidate occurrence is ambiguous")
    if not selection.decision_range.contains_block(_number(values["block_ordinal"])):
        raise ValueError("candidate is outside decision range")


def _row_digest(values: dict[str, object], columns: tuple[str, ...]) -> ContentDigest:
    """Raw source bytes are hashed only inside bounded preparation, never used as event ID."""
    return domain_digest(
        "backtest.copy-candidate-row.v1", [[name, _source_value(values[name])] for name in columns]
    )


def _source_value(value: object) -> object:
    """Preserve byte strings and exact source timestamps without lossy text coercion."""
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, datetime):
        return {"unix_ns": _block_time(value)[0]}
    if type(value) in (str, int) or value is None:
        # Unrecognized source types reject evidence instead of receiving a lossy string coercion.
        return value
    raise ValueError("unsupported raw candidate value")


def _number(value: object) -> int:
    """Reject booleans, floats and missing values at the source proof boundary."""
    if type(value) is not int or value < 0:
        raise ValueError("copy source requires a nonnegative integer")
    return value


def _text(value: object) -> str:
    """Closed source enums may be text or their exact ASCII wire bytes."""
    if isinstance(value, bytes):
        return value.decode("ascii")
    if not isinstance(value, str):
        raise ValueError("copy source requires text")
    return value


def build_pumpfun_copy_source_composition(
    capabilities: tuple[ClickHouseCapability, ...],
    selection: CopySourceSelection,
    *,
    build_tools: PinnedCodeBundleSet,
    # The configured query policy supplies hard limits, never semantic source proof.
    query_policy: ClickHouseQueryPolicy | None = None,
) -> PumpfunCopySourceComposition:
    """Wire a closed normalized schema and signer-bearing projector without arbitrary aliases."""
    base = build_pumpfun_live_source_composition(capabilities, query_policy=query_policy)
    normalizer = PumpfunCopyBuyLiveNormalizer(base.normalizer.fee_profile)
    profile = PumpfunCopyBuyQueryProfile(selection, base._profile)
    # Normalized descriptors are built for every declared source capability.
    metadata = tuple(
        _normalized_descriptor(item, normalizer, projection=False)
        for item in capabilities
        # Metadata describes normalized columns while projection keeps their physical mappings.
    )
    projection = tuple(_projection_capability(item, normalizer) for item in capabilities)
    # A separate trade schema prevents signerless normalized artifacts from being reused.
    metadata = tuple(
        replace(item, schema_version="pumpfun-copybuy-curve-trade-normalized-v1")
        if item.stream is CapabilityStream.PUMP_CURVE_TRADE
        else item
        for item in metadata
        # Copy trades receive their own schema version; other stream meanings stay unchanged.
    )
    projection = tuple(
        replace(
            item,
            descriptor=replace(
                # The projector descriptor must advertise the same actor-bearing trade schema.
                item.descriptor,
                schema_version="pumpfun-copybuy-curve-trade-normalized-v1",
            ),
        )
        # Only trade descriptors change version to carry the additional actor payload.
        if item.descriptor.stream is CapabilityStream.PUMP_CURVE_TRADE
        else item
        # Every declared projection capability is retained in canonical stream order.
        for item in projection
    )
    digest = domain_digest(
        "backtest.pumpfun-copy-source-normalization.v1",
        {
            # Normalizer identity binds the shared raw contract and the complete copy selection.
            "shared_source_contract": base.normalizer_digest.hex,
            "copy_normalizer": normalizer.config_digest.hex,
            "selection": selection.document(),
        },
    )
    # Fixed identity fields prevent aliases from changing actor meaning.
    kinds = dict(
        zip(
            _STREAM_ORDER,
            (
                EventKindName.BLOCK,
                # Launch and market kinds remain distinct so initialization cannot become a buy
                # signal.
                EventKindName.TOKEN_LAUNCH,
                EventKindName.VENUE_TRADE,
                EventKindName.VENUE_LIFECYCLE,
            ),
            strict=True,
            # Strict zip rejects missing stream declarations rather than truncating the mapping.
        )
    )
    payloads = dict(
        zip(
            _STREAM_ORDER,
            # Clock rows have no protocol payload; trades explicitly carry their signer schema.
            (
                None,
                PUMPFUN_LAUNCH_PAYLOAD_SCHEMA_ID,
                COPYBUY_TRADE_PAYLOAD_SCHEMA,
                PUMPFUN_LIFECYCLE_PAYLOAD_SCHEMA_ID,
                # Lifecycle decoding retains the existing atomic completion and migration contract.
            ),
            strict=True,
        )
    )
    specs = tuple(
        # Projection specs bind payload shape, ordering and source identity per capability.
        PumpfunProjectionSpec(
            item.descriptor.capability_id,
            kinds[item.descriptor.stream],
            item.descriptor.protocol,
            item.descriptor.protocol_version,
            # Source event identity fidelity is preserved independently of payload content.
            item.descriptor.fidelity.identity,
            # All logical source fields retain their exact normalized names in canonical projection.
            item.descriptor.fidelity.ordering,
            item.descriptor.total_key,
            True,
            payloads[item.descriptor.stream],
            # Only mint and creator have semantic aliases; signing_wallet remains physically exact.
            tuple(
                ({"mint": "asset", "creator": "developer"}.get(column, column), column)
                for column in item.descriptor.columns
            ),
        )
        # The source mapping is frozen before the projector computes its config digest.
        for item in projection
    )
    projector = PumpfunProtocolProjector(
        network_id=selection.decision_range.network_id,
        position_schema_id=selection.decision_range.position_schema_id,
        # Network and position schema come from the typed selection, not the endpoint.
        specs=specs,
        source_normalizer_digest=digest,
        build_tools=build_tools,
    )
    return PumpfunCopySourceComposition(
        # The composition owns concrete adapters while exposing the existing source port.
        base.raw_capabilities,
        metadata,
        projection,
        base.query_policy,
        normalizer,
        # Mapping and query digests remain separate from the normalizer and projector digests.
        base.capability_mapping_digest,
        profile.template_digest,
        digest,
        base._profile,
        selection,
        # The fixed copy query profile and projector are injected only at this composition root.
        profile,
        projector,
    )
