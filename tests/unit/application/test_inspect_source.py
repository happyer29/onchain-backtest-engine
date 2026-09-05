# Declare this module's dependencies and contracts before execution.
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from backtest.application.errors import (
    ErrorCode,
    SourceEvidenceValidationError,
    SourceInspectionFailedError,
)
from backtest.application.models import (
    # Include bounded source evidence request so the models dependency remains explicit.
    BoundedSourceEvidenceRequest,
    CapabilityCutEvidence,
    CapabilityDescriptor,
    CapabilityProofs,
    CapabilityStream,
    # Include evidence status so the models dependency remains explicit.
    EvidenceStatus,
    QueryLimits,
    SourceColumn,
    SourceMetadata,
    SourceTable,
    # Include build bounded source evidence receipt so the models dependency remains
    # explicit.
    build_bounded_source_evidence_receipt,
)
from backtest.application.sniping_run_contract import PUMPFUN_SNIPING_UNIVERSE_POLICY_ID
from backtest.application.source_evidence import (
    PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID,
    SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
)
from backtest.application.use_cases.inspect_source import InspectSource, InspectSourceRequest
from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    # Include solana mainnet network id so the chain dependency remains explicit.
    SOLANA_MAINNET_NETWORK_ID,
)
from backtest.domain.fidelity import (
    ChainFinality,
    FeesFidelity,
    # Include identity fidelity so the fidelity dependency remains explicit.
    IdentityFidelity,
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    # Include state fidelity so the fidelity dependency remains explicit.
    StateFidelity,
)
from backtest.domain.identifiers import CapabilityId, ContentDigest, SourceId
from backtest.domain.time import BlockRange


def _fidelity() -> SourceFidelity:
    # Execute the fidelity workflow in explicit, reviewable steps.
    return SourceFidelity(
        identity=IdentityFidelity.CANDIDATE,
        ordering=OrderingFidelity.TRANSACTION_EXACT,
        state=StateFidelity.AFTER_ONLY,
        fees=FeesFidelity.COMPONENTS,
        # Pass chain finality explicitly so SourceFidelity receives a reviewable candidate
        # and transaction exact input in fidelity.
        chain_finality=ChainFinality.UNKNOWN,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )


def _metadata(source_id: SourceId, *, reverse: bool = False) -> SourceMetadata:
    # Execute the metadata workflow in explicit, reviewable steps.
    columns = (
        SourceColumn("slot", "UInt64", False),
        SourceColumn("signature", "String", False),
    )
    if reverse:
        # Assemble columns once so the metadata workflow shares one value.
        columns = tuple(reversed(columns))
    tables = (
        SourceTable(
            name="pumpfun_v2_swaps",
            engine="MergeTree",
            # Pass partition key explicitly so SourceTable receives a reviewable pumpfun
            # v2 swaps and merge tree input in metadata.
            partition_key="block_date_utc",
            sorting_key="(slot, tx_idx)",
            columns=columns,
        ),
    )
    # Return the completed metadata result without a hidden fallback.
    return SourceMetadata(
        source_id=source_id,
        network_id=SOLANA_MAINNET_NETWORK_ID,
        position_schema_id=BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        server_version="24.6.2.17",
        # Pass tables explicitly so SourceMetadata receives a reviewable 17 and pumpfun
        # input in metadata.
        tables=tables,
        capabilities=(
            CapabilityDescriptor(
                capability_id=CapabilityId("pumpfun.swaps.v1"),
                protocol="pumpfun",
                # Pass protocol version explicitly so CapabilityDescriptor receives a
                # reviewable v1 and pumpfun input in metadata.
                protocol_version="v2",
                schema_version="1",
                stream=CapabilityStream.PUMP_CURVE_TRADE,
                columns=("block_ordinal", "signature"),
                mandatory_columns=("block_ordinal",),
                # Include fidelity in the completed metadata result.
                fidelity=_fidelity(),
                total_key=("signature",),
                keyset_key_is_proven=False,
                utc_pruning_column="block_date_utc",
                utc_pruning_is_proven=True,
                # Complete CapabilityDescriptor only after its v1 and pumpfun inputs are
                # visible in metadata.
            ),
        ),
        capability_mapping_digest=ContentDigest("b" * 64),
        query_template_digest=ContentDigest("c" * 64),
    )


# Keep the reader contract and validation rules together.
class _Reader:
    def __init__(self, metadata: SourceMetadata) -> None:
        # Execute the reader init workflow in explicit, reviewable steps.
        self.metadata = metadata
        self.calls = 0

    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        # Execute the reader inspect metadata workflow in explicit, reviewable steps.
        assert source_id == self.metadata.source_id
        self.calls += 1
        return self.metadata


# Keep the evidence reader contract and validation rules together.
class _EvidenceReader:
    def __init__(self, receipt) -> None:
        # Execute the evidence reader init workflow in explicit, reviewable steps.
        self.receipt = receipt
        self.calls = 0

    def inspect_bounded_evidence(self, request: BoundedSourceEvidenceRequest):
        # Execute the evidence reader inspect bounded evidence workflow in explicit,
        # reviewable steps.
        assert request.source_id == self.receipt.source_id
        self.calls += 1
        return (self.receipt,)


class _FailingEvidenceReader:
    def __init__(self, code: ErrorCode) -> None:
        self.code = code

    def inspect_bounded_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
    ) -> tuple[()]:
        del request
        try:
            raise RuntimeError("password=bounded-evidence-secret")
        except RuntimeError as error:
            raise SourceEvidenceValidationError(self.code) from error


class _LeakyEvidenceReader:
    def inspect_bounded_evidence(
        self,
        request: BoundedSourceEvidenceRequest,
    ) -> tuple[()]:
        del request
        raise RuntimeError("password=unknown-bounded-driver-secret")


def _evidence_request(source_id: SourceId) -> BoundedSourceEvidenceRequest:
    # Execute the evidence request workflow in explicit, reviewable steps.
    block_range = BlockRange(
        SOLANA_MAINNET_NETWORK_ID,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        100,
        101,
    )
    return BoundedSourceEvidenceRequest(
        source_id=source_id,
        block_range=block_range,
        decision_range=block_range,
        capability_mapping_digest=ContentDigest("b" * 64),
        query_template_digest=ContentDigest("c" * 64),
        projector_digest=ContentDigest("1" * 64),
        normalizer_digest=ContentDigest("2" * 64),
        launch_universe_policy_id=PUMPFUN_SNIPING_UNIVERSE_POLICY_ID,
        skipped_slot_sentinel_policy_id=SOLANA_SKIPPED_SLOT_SENTINEL_POLICY_ID,
        terminal_lifecycle_ordering_policy_id=(PUMPFUN_TERMINAL_LIFECYCLE_ORDERING_POLICY_ID),
        query_limits=QueryLimits(10, 64 * 1024**2, 100),
    )


# Define receipt as one focused operation with an explicit boundary.
def _receipt(source_id: SourceId, *, mapping_digest: str = "b" * 64):
    # Execute the receipt workflow in explicit, reviewable steps.
    metadata = _metadata(source_id)
    descriptor = metadata.capabilities[0]
    proofs = CapabilityProofs(
        global_zero_based_transaction_index=EvidenceStatus.REFUTED,
    )
    # Assemble cut once so the receipt workflow shares one value.
    cut = CapabilityCutEvidence(
        capability_id=descriptor.capability_id,
        block_range=_evidence_request(source_id).block_range,
        snapshot_cut_to_block=101,
        chain_finality=ChainFinality.UNKNOWN,
        # Pass ingestion watermark to block explicitly so CapabilityCutEvidence receives a
        # reviewable capability id and block range input in receipt.
        ingestion_watermark_to_block=None,
        completeness=IngestionCompleteness.UNKNOWN,
        consistency=SourceConsistency.UNKNOWN,
    )
    return build_bounded_source_evidence_receipt(
        # Pass source id explicitly so build_bounded_source_evidence_receipt receives a
        # reviewable c and d input in receipt.
        source_id=source_id,
        capability_id=descriptor.capability_id,
        protocol_version=descriptor.protocol_version,
        capability_schema_version=descriptor.schema_version,
        capability_mapping_digest=ContentDigest(mapping_digest),
        # Include query template digest in the completed receipt result.
        query_template_digest=ContentDigest("c" * 64),
        projector_digest=ContentDigest("1" * 64),
        normalizer_digest=ContentDigest("2" * 64),
        cut_evidence=cut,
        decision_range=_evidence_request(source_id).decision_range,
        proofs=proofs,
        source_fidelity=SourceFidelity(
            identity=IdentityFidelity.EXACT,
            ordering=OrderingFidelity.INSTRUCTION_EXACT,
            state=StateFidelity.AFTER_ONLY,
            fees=FeesFidelity.COMPONENTS,
            chain_finality=cut.chain_finality,
            completeness=cut.completeness,
            consistency=cut.consistency,
        ),
        query_fingerprints=(ContentDigest("d" * 64),),
        result_digest=ContentDigest("e" * 64),
        # Pass observed rows explicitly so build_bounded_source_evidence_receipt receives
        # a reviewable c and d input in receipt.
        observed_rows=1,
    )


def test_inspection_is_immutable_and_fingerprint_is_operational_time_independent() -> None:
    # Execute the test inspection is immutable and fingerprint is operational time
    # independent workflow in explicit, reviewable steps.
    source_id = SourceId("readonly-indexer")
    reader = _Reader(_metadata(source_id))
    first = InspectSource(
        reader,
        now=lambda: datetime(2026, 8, 31, 10, tzinfo=UTC),
        # Keep the source id InspectSourceRequest step visible while building first.
    ).execute(InspectSourceRequest(source_id))
    second = InspectSource(
        reader,
        now=lambda: datetime(2026, 9, 1, 10, tzinfo=UTC),
    ).execute(InspectSourceRequest(source_id))

    # Verify the schema fingerprint, first and second relationship before this scenario is
    # accepted.
    assert first.schema_fingerprint == second.schema_fingerprint
    assert first.inspected_at != second.inspected_at
    assert reader.calls == 2
    with pytest.raises(FrozenInstanceError):
        first.inspected_at = datetime.now(UTC)  # type: ignore[misc]


def test_fingerprint_is_independent_of_metadata_input_order_and_source_id() -> None:
    # Execute the test fingerprint is independent of metadata input order and source id
    # workflow in explicit, reviewable steps.
    first_source = SourceId("source-a")
    second_source = SourceId("source-b")
    first = InspectSource(
        _Reader(_metadata(first_source)),
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
        # Keep the first source InspectSourceRequest step visible while building first.
    ).execute(InspectSourceRequest(first_source))
    second = InspectSource(
        _Reader(_metadata(second_source, reverse=True)),
        now=lambda: datetime(2026, 8, 31, tzinfo=UTC),
    ).execute(InspectSourceRequest(second_source))

    # Verify the schema fingerprint, first and second relationship before this scenario is
    # accepted.
    assert first.schema_fingerprint == second.schema_fingerprint


def test_fingerprint_normalizes_the_optional_digest_display_prefix() -> None:
    # Execute the test fingerprint normalizes the optional digest display prefix workflow
    # in explicit, reviewable steps.
    source_id = SourceId("source-a")
    metadata = _metadata(source_id)
    digest_hex = "a" * 64

    prefixed = replace(
        metadata,
        # Keep the content digest and sha256: ContentDigest step visible while building
        # prefixed.
        query_template_digest=ContentDigest(f"sha256:{digest_hex}"),
    )
    plain = replace(metadata, query_template_digest=ContentDigest(digest_hex))

    first = InspectSource(_Reader(prefixed)).execute(InspectSourceRequest(source_id))
    second = InspectSource(_Reader(plain)).execute(InspectSourceRequest(source_id))

    # Verify the schema fingerprint, first and second relationship before this scenario is
    # accepted.
    assert first.schema_fingerprint == second.schema_fingerprint


def test_bounded_evidence_is_promoted_only_through_the_explicit_port() -> None:
    # Execute the test bounded evidence is promoted only through the explicit port
    # workflow in explicit, reviewable steps.
    source_id = SourceId("source-a")
    metadata = _metadata(source_id)
    evidence_reader = _EvidenceReader(_receipt(source_id))
    bare = InspectSource(_Reader(metadata)).execute(InspectSourceRequest(source_id))

    bounded = InspectSource(
        # Keep the metadata _Reader step visible while building bounded.
        _Reader(metadata),
        evidence_reader=evidence_reader,
    ).execute(InspectSourceRequest(source_id, _evidence_request(source_id)))

    assert evidence_reader.calls == 1
    assert len(bounded.metadata.evidence_receipts) == 1
    # Verify the global zero based transaction index, refuted and proofs relationship
    # before this scenario is accepted.
    assert (
        bounded.metadata.capabilities[0].proofs.global_zero_based_transaction_index
        is EvidenceStatus.REFUTED
    )
    assert bounded.metadata.capabilities[0].fidelity.identity is IdentityFidelity.EXACT
    assert bounded.metadata.cut_evidence == (bounded.metadata.evidence_receipts[0].cut_evidence,)
    # Bounded evidence changes cut claims, not the declarative source schema.
    assert bounded.schema_fingerprint == bare.schema_fingerprint


def test_bounded_evidence_must_match_the_inspected_mapping() -> None:
    # Execute the test bounded evidence must match the inspected mapping workflow in
    # explicit, reviewable steps.
    source_id = SourceId("source-a")
    reader = _EvidenceReader(_receipt(source_id, mapping_digest="f" * 64))

    with pytest.raises(SourceInspectionFailedError):
        # Keep raises, source inspection failed error and pytest active only for the
        # bounded test bounded evidence must match the inspected mapping operation.
        InspectSource(
            _Reader(_metadata(source_id)),
            evidence_reader=reader,
        ).execute(InspectSourceRequest(source_id, _evidence_request(source_id)))


def test_metadata_cannot_carry_a_manual_proven_claim_without_a_receipt() -> None:
    # Execute the test metadata cannot carry a manual proven claim without a receipt
    # workflow in explicit, reviewable steps.
    source_id = SourceId("source-a")
    metadata = _metadata(source_id)
    forged_descriptor = replace(
        metadata.capabilities[0],
        proofs=CapabilityProofs(
            # Pass global zero based transaction index explicitly so CapabilityProofs
            # receives a reviewable proven and evidence status input in test metadata
            # cannot carry a manual proven claim without a receipt.
            global_zero_based_transaction_index=EvidenceStatus.PROVEN,
        ),
    )

    with pytest.raises(ValueError, match="lacks bounded evidence provenance"):
        replace(metadata, capabilities=(forged_descriptor,))


# Keep the leaky reader contract and validation rules together.
class _LeakyReader:
    def inspect_metadata(self, source_id: SourceId) -> SourceMetadata:
        # Execute the leaky reader inspect metadata workflow in explicit, reviewable
        # steps.
        del source_id
        raise RuntimeError("password=fixture-must-not-escape")


def test_adapter_exception_is_replaced_with_safe_typed_error() -> None:
    # Execute the test adapter exception is replaced with safe typed error workflow in
    # explicit, reviewable steps.
    source_id = SourceId("readonly-indexer")
    with pytest.raises(SourceInspectionFailedError) as caught:
        InspectSource(_LeakyReader()).execute(InspectSourceRequest(source_id))

    assert caught.value.code is ErrorCode.SOURCE_INSPECTION_FAILED
    assert "must-not-escape" not in str(caught.value)
    # Verify caught.value.__cause__ is None before this scenario is accepted.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "code",
    (ErrorCode.INCOMPLETE_BLOCK_RANGE, ErrorCode.CURVE_TRANSITION_MISMATCH),
)
def test_bounded_evidence_rejection_preserves_only_its_safe_stable_code(
    code: ErrorCode,
) -> None:
    source_id = SourceId("readonly-indexer")

    with pytest.raises(SourceEvidenceValidationError) as caught:
        InspectSource(
            _Reader(_metadata(source_id)),
            evidence_reader=_FailingEvidenceReader(code),
        ).execute(InspectSourceRequest(source_id, _evidence_request(source_id)))

    assert caught.value.code is code
    assert code.value in caught.value.code.value
    assert "bounded-evidence-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_unknown_bounded_evidence_exception_remains_generic_and_redacted() -> None:
    source_id = SourceId("readonly-indexer")

    with pytest.raises(SourceInspectionFailedError) as caught:
        InspectSource(
            _Reader(_metadata(source_id)),
            evidence_reader=_LeakyEvidenceReader(),
        ).execute(InspectSourceRequest(source_id, _evidence_request(source_id)))

    assert caught.value.code is ErrorCode.SOURCE_INSPECTION_FAILED
    assert "unknown-bounded-driver-secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
