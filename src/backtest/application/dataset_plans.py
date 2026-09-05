"""Canonical codec for an exact executable :class:`DatasetPlan`."""

from __future__ import annotations

import json
from typing import cast

from backtest.application.errors import ReprepareRequiredError
from backtest.application.models import (
    # Include capability proof fields so the models dependency remains explicit.
    CAPABILITY_PROOF_FIELDS,
    BudgetIssue,
    BudgetIssueKind,
    BudgetReport,
    BudgetStatus,
    # Include capability cut evidence so the models dependency remains explicit.
    CapabilityCutEvidence,
    CapabilityExtractionRange,
    CapabilityProofs,
    CapabilityStream,
    DatasetPlan,
    # Include dataset shard so the models dependency remains explicit.
    DatasetShard,
    DatasetSpec,
    EvidenceStatus,
    PlannedCapability,
    QueryLimits,
    # Include settlement requirement so the models dependency remains explicit.
    SettlementRequirement,
)
from backtest.application.source_evidence import (
    LaunchUniverseEvidence,
    PumpfunSnipingSourceEvidenceBinding,
    SkippedSlotSentinelEvidence,
    SourceEvidenceReceiptRef,
    TerminalLifecycleOrderingEvidence,
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
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    # Include capability id so the identifiers dependency remains explicit.
    CapabilityId,
    ContentDigest,
    NetworkId,
    PositionSchemaId,
    SourceId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.time import BlockRange


class DatasetPlanCodecError(ValueError):
    """The plan document is non-canonical, malformed or identity-inconsistent."""


def dataset_plan_bytes(plan: DatasetPlan) -> bytes:
    return canonical_json_bytes(_document(plan))


def dataset_plan_from_bytes(payload: bytes) -> DatasetPlan:
    # Execute the dataset plan from bytes workflow in explicit, reviewable steps.
    try:
        # Perform the protected dataset plan from bytes operation before explicit failure
        # handling.
        value = json.loads(payload)
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise DatasetPlanCodecError("dataset plan must be canonical JSON") from error
    if canonical != payload:
        # Fail the dataset plan from bytes path with DatasetPlanCodecError for dataset
        # plan is not in exact canonical form when canonical and payload is true; do not
        # continue ambiguously.
        raise DatasetPlanCodecError("dataset plan is not in exact canonical form")
    document = _object(value, "dataset plan")
    schema = document.get("schema")
    if schema in {
        "backtest.dataset-plan/v1",
        "backtest.dataset-plan/v2",
        "backtest.dataset-plan/v3",
    }:
        raise ReprepareRequiredError(str(schema))
    _keys(document, {"budget", "query_limits", "schema", "spec"}, "dataset plan")
    # Evaluate the complete dataset plan from bytes document and schema condition before
    # guarded effects.
    if schema != "backtest.dataset-plan/v4":
        raise DatasetPlanCodecError("unsupported dataset plan schema")
    try:
        # Perform the protected dataset plan from bytes operation before explicit failure
        # handling.
        result = DatasetPlan(
            spec=_spec(document["spec"]),
            budget=_budget(document["budget"]),
            query_limits=_query_limits(document["query_limits"]),
        )
    # Translate key error through the dataset plan from bytes boundary without hiding
    # other errors.
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the dataset plan
        # from bytes boundary.
        if isinstance(error, DatasetPlanCodecError):
            raise
        raise DatasetPlanCodecError("dataset plan fields are invalid") from error
    if dataset_plan_bytes(result) != payload:
        raise DatasetPlanCodecError("dataset plan does not round-trip exactly")
    # Return the completed dataset plan from bytes result without a hidden fallback.
    return result


def dataset_spec_document(spec: DatasetSpec) -> dict[str, object]:
    """Return the strict canonical document embedded by derived artifacts."""

    return _spec_document(spec)


def dataset_spec_from_document(value: object) -> DatasetSpec:
    """Decode and identity-check one embedded DatasetSpec document."""

    document = _object(value, "dataset spec")
    version = document.get("spec_version")
    if not isinstance(version, bool) and version in (1, 2, 3, 4):
        raise ReprepareRequiredError(f"backtest.dataset-spec/v{version}")
    if version != 5:
        # Fail the dataset spec from document path with DatasetPlanCodecError for
        # unsupported dataset spec schema when version is true; do not continue
        # ambiguously.
        raise DatasetPlanCodecError("unsupported dataset spec schema")
    try:
        return _spec(document)
    except (KeyError, TypeError, ValueError) as error:
        # Translate the (KeyError, TypeError, ValueError) failure through the dataset spec
        # from document boundary.
        if isinstance(error, DatasetPlanCodecError):
            raise
        raise DatasetPlanCodecError("dataset spec fields are invalid") from error


def _document(plan: DatasetPlan) -> dict[str, object]:
    # Execute the document workflow in explicit, reviewable steps.
    spec = plan.spec
    budget = plan.budget
    return {
        "budget": {
            "current_free_disk_bytes": budget.current_free_disk_bytes,
            # Include disk low watermark bytes in the completed document result.
            "disk_low_watermark_bytes": budget.disk_low_watermark_bytes,
            "estimated_source_bytes": budget.estimated_source_bytes,
            "estimated_source_rows": budget.estimated_source_rows,
            "expected_local_parquet_bytes": budget.expected_local_parquet_bytes,
            "issues": [
                # Return the completed document result without a hidden fallback.
                {
                    "actual": item.actual,
                    "code": item.code,
                    "kind": item.kind.value,
                    "limit": item.limit,
                    # Include message in the completed document result.
                    "message": item.message,
                }
                for item in budget.issues
            ],
            "max_days": budget.max_days,
            # Include max local bytes in the completed document result.
            "max_local_bytes": budget.max_local_bytes,
            "max_remote_bytes": budget.max_remote_bytes,
            "max_shard_blocks": budget.max_shard_blocks,
            "max_total_shards": budget.max_total_shards,
            "max_total_blocks": budget.max_total_blocks,
            # Include planned shards in the completed document result.
            "planned_shards": budget.planned_shards,
            "requested_days": budget.requested_days,
            "requested_blocks": budget.requested_blocks,
            "status": budget.status.value,
            "temporary_reserve_bytes": budget.temporary_reserve_bytes,
            # Return the completed document result without a hidden fallback.
        },
        "query_limits": {
            "max_execution_seconds": plan.query_limits.max_execution_seconds,
            "max_memory_bytes": plan.query_limits.max_memory_bytes,
            "max_result_rows": plan.query_limits.max_result_rows,
            # Return the completed document result without a hidden fallback.
        },
        "schema": "backtest.dataset-plan/v4",
        "spec": _spec_document(spec),
    }


def _spec_document(spec: DatasetSpec) -> dict[str, object]:
    # Execute the spec document workflow in explicit, reviewable steps.
    return {
        "capability_ranges": [
            {
                "block_range": _range_document(item.block_range),
                "capability_id": item.capability_id.value,
                # Return the completed spec document result without a hidden fallback.
            }
            for item in spec.capability_ranges
        ],
        "capabilities": [_capability_document(item) for item in spec.capabilities],
        "capability_mapping_digest": spec.capability_mapping_digest.hex,
        # Include cut evidence in the completed spec document result.
        "cut_evidence": [_evidence_document(item) for item in spec.cut_evidence],
        "decision_range": _range_document(spec.decision_range),
        "evidence_contracts": list(spec.evidence_contracts),
        "network_id": spec.network_id.value,
        "position_schema_id": spec.position_schema_id.value,
        # Include query template digest in the completed spec document result.
        "query_template_digest": spec.query_template_digest.hex,
        "settlement_tail": (
            None if spec.settlement_tail is None else _range_document(spec.settlement_tail)
        ),
        "settlement_requirement": _settlement_requirement_document(spec.settlement_requirement),
        "source_evidence_binding": _source_evidence_binding_document(spec.source_evidence_binding),
        # Include shards in the completed spec document result.
        "shards": [
            {
                "capability_id": item.capability_id.value,
                "columns": list(item.columns),
                "ordinal": item.ordinal,
                # Include block range in the completed spec document result.
                "block_range": _range_document(item.block_range),
            }
            for item in spec.shards
        ],
        "source_id": spec.source_id.value,
        # Include source inspection artifact id in the completed spec document result.
        "source_inspection_artifact_id": spec.source_inspection_artifact_id.hex,
        "source_schema_fingerprint": spec.source_schema_fingerprint.hex,
        "spec_id": spec.spec_id.hex,
        "spec_version": spec.spec_version,
        "warmup_blocks": spec.warmup_blocks,
        # Return the completed spec document result without a hidden fallback.
    }


def _spec(value: object) -> DatasetSpec:
    # Execute the spec workflow in explicit, reviewable steps.
    document = _object(value, "dataset spec")
    _keys(
        document,
        {
            "capability_ranges",
            # Pass capabilities explicitly so _keys receives a reviewable capability
            # ranges and capabilities input in spec.
            "capabilities",
            "capability_mapping_digest",
            "cut_evidence",
            "decision_range",
            "evidence_contracts",
            # Pass network id explicitly so _keys receives a reviewable capability ranges
            # and capabilities input in spec.
            "network_id",
            "position_schema_id",
            "query_template_digest",
            "settlement_tail",
            "settlement_requirement",
            "source_evidence_binding",
            # Pass shards explicitly so _keys receives a reviewable capability ranges and
            # capabilities input in spec.
            "shards",
            "source_id",
            "source_inspection_artifact_id",
            "source_schema_fingerprint",
            "spec_id",
            # Pass spec version explicitly so _keys receives a reviewable capability
            # ranges and capabilities input in spec.
            "spec_version",
            "warmup_blocks",
        },
        "dataset spec",
    )
    # Return the completed spec result without a hidden fallback.
    return DatasetSpec(
        spec_version=_integer(document["spec_version"], "spec_version", minimum=1),
        spec_id=ContentDigest(_string(document["spec_id"], "spec_id")),
        source_id=SourceId(_string(document["source_id"], "source_id")),
        source_inspection_artifact_id=ArtifactId(
            # Include string in the completed spec result.
            _string(
                document["source_inspection_artifact_id"],
                "source_inspection_artifact_id",
            )
        ),
        # Include source schema fingerprint in the completed spec result.
        source_schema_fingerprint=ContentDigest(
            _string(document["source_schema_fingerprint"], "source_schema_fingerprint")
        ),
        capability_mapping_digest=ContentDigest(
            _string(document["capability_mapping_digest"], "capability_mapping_digest")
            # Complete ContentDigest only after its capability mapping digest and string
            # inputs are visible in spec.
        ),
        query_template_digest=ContentDigest(
            _string(document["query_template_digest"], "query_template_digest")
        ),
        network_id=NetworkId(_string(document["network_id"], "network_id")),
        # Include position schema id in the completed spec result.
        position_schema_id=PositionSchemaId(
            _string(document["position_schema_id"], "position_schema_id")
        ),
        decision_range=_range(document["decision_range"], "decision_range"),
        settlement_tail=_optional_range(document["settlement_tail"], "settlement_tail"),
        # Include warmup blocks in the completed spec result.
        warmup_blocks=_integer(document["warmup_blocks"], "warmup_blocks"),
        evidence_contracts=_strings(document["evidence_contracts"], "evidence_contracts"),
        capabilities=tuple(
            _capability(item) for item in _list(document["capabilities"], "capabilities")
        ),
        # Include capability ranges in the completed spec result.
        capability_ranges=tuple(
            _capability_range(item)
            for item in _list(document["capability_ranges"], "capability_ranges")
        ),
        cut_evidence=tuple(
            # Include evidence in the completed spec result.
            _evidence(item)
            for item in _list(document["cut_evidence"], "cut_evidence")
        ),
        shards=tuple(_shard(item) for item in _list(document["shards"], "shards")),
        settlement_requirement=_settlement_requirement(document["settlement_requirement"]),
        source_evidence_binding=_source_evidence_binding(document["source_evidence_binding"]),
        # Complete DatasetSpec only after its spec version and spec id inputs are visible in
        # spec.
    )


def _source_evidence_binding_document(
    value: PumpfunSnipingSourceEvidenceBinding | None,
) -> dict[str, object] | None:
    return None if value is None else value.identity_document()


def _source_evidence_binding(
    value: object,
) -> PumpfunSnipingSourceEvidenceBinding | None:
    if value is None:
        return None
    document = _object(value, "source evidence binding")
    _keys(
        document,
        {
            "capability_mapping_digest",
            "launch_universe",
            "normalizer_digest",
            "projector_digest",
            "query_template_digest",
            "receipt_refs",
            "schema",
            "skipped_slot_sentinel",
            "terminal_lifecycle_ordering",
        },
        "source evidence binding",
    )
    return PumpfunSnipingSourceEvidenceBinding(
        receipt_refs=tuple(
            _source_evidence_receipt_ref(item)
            for item in _list(document["receipt_refs"], "source evidence receipt refs")
        ),
        capability_mapping_digest=ContentDigest(
            _string(document["capability_mapping_digest"], "capability_mapping_digest")
        ),
        query_template_digest=ContentDigest(
            _string(document["query_template_digest"], "query_template_digest")
        ),
        projector_digest=ContentDigest(_string(document["projector_digest"], "projector_digest")),
        normalizer_digest=ContentDigest(
            _string(document["normalizer_digest"], "normalizer_digest")
        ),
        launch_universe=_launch_universe(document["launch_universe"]),
        skipped_slot_sentinel=_skipped_slot_sentinel(document["skipped_slot_sentinel"]),
        terminal_lifecycle_ordering=_terminal_lifecycle_ordering(
            document["terminal_lifecycle_ordering"]
        ),
        schema=_string(document["schema"], "source evidence binding schema"),
    )


def _source_evidence_receipt_ref(value: object) -> SourceEvidenceReceiptRef:
    document = _object(value, "source evidence receipt ref")
    _keys(
        document,
        {"capability_id", "receipt_id"},
        "source evidence receipt ref",
    )
    return SourceEvidenceReceiptRef(
        capability_id=CapabilityId(_string(document["capability_id"], "capability_id")),
        receipt_id=ContentDigest(_string(document["receipt_id"], "receipt_id")),
    )


def _launch_universe(value: object) -> LaunchUniverseEvidence:
    document = _object(value, "launch universe evidence")
    _keys(
        document,
        {
            "classified_count",
            "decision_range",
            "eligible_count",
            "excluded_count",
            "exclusion_reason",
            "ordered_exclusion_digest",
            "policy_id",
            "schema",
        },
        "launch universe evidence",
    )
    return LaunchUniverseEvidence(
        decision_range=_range(document["decision_range"], "decision_range"),
        policy_id=_string(document["policy_id"], "launch universe policy_id"),
        classified_count=_integer(document["classified_count"], "classified_count"),
        eligible_count=_integer(document["eligible_count"], "eligible_count"),
        excluded_count=_integer(document["excluded_count"], "excluded_count"),
        ordered_exclusion_digest=ContentDigest(
            _string(document["ordered_exclusion_digest"], "ordered_exclusion_digest")
        ),
        exclusion_reason=_string(document["exclusion_reason"], "exclusion_reason"),
        schema=_string(document["schema"], "launch universe evidence schema"),
    )


def _skipped_slot_sentinel(value: object) -> SkippedSlotSentinelEvidence:
    document = _object(value, "skipped-slot sentinel evidence")
    _keys(
        document,
        {"ordered_sentinel_digest", "profile_id", "recognized_count", "schema"},
        "skipped-slot sentinel evidence",
    )
    return SkippedSlotSentinelEvidence(
        profile_id=_string(document["profile_id"], "sentinel profile_id"),
        recognized_count=_integer(document["recognized_count"], "recognized_count"),
        ordered_sentinel_digest=ContentDigest(
            _string(document["ordered_sentinel_digest"], "ordered_sentinel_digest")
        ),
        schema=_string(document["schema"], "sentinel evidence schema"),
    )


def _terminal_lifecycle_ordering(value: object) -> TerminalLifecycleOrderingEvidence:
    document = _object(value, "terminal lifecycle ordering evidence")
    _keys(
        document,
        {"derived_group_count", "ordered_group_digest", "profile_id", "schema"},
        "terminal lifecycle ordering evidence",
    )
    return TerminalLifecycleOrderingEvidence(
        profile_id=_string(document["profile_id"], "lifecycle ordering profile_id"),
        derived_group_count=_integer(
            document["derived_group_count"],
            "derived_group_count",
        ),
        ordered_group_digest=ContentDigest(
            _string(document["ordered_group_digest"], "ordered_group_digest")
        ),
        schema=_string(document["schema"], "lifecycle ordering evidence schema"),
    )


# Define settlement requirement document as one focused operation with an explicit
# boundary.
def _settlement_requirement_document(
    value: SettlementRequirement | None,
) -> dict[str, object] | None:
    # Execute the settlement requirement document workflow in explicit, reviewable steps.
    if value is None:
        return None
    return {
        "initial_delay_transactions": value.initial_delay_transactions,
        "maximum_followup_delay_transactions": value.maximum_followup_delay_transactions,
        # Include maximum tail blocks in the completed settlement requirement document
        # result.
        "maximum_tail_blocks": value.maximum_tail_blocks,
        "minimum_duration_ns": value.minimum_duration_ns,
        "schema": value.schema,
        "settlement_streams": [item.value for item in value.settlement_streams],
        "target_stream": value.target_stream.value,
        # Return the completed settlement requirement document result without a hidden
        # fallback.
    }


def _settlement_requirement(value: object) -> SettlementRequirement | None:
    # Execute the settlement requirement workflow in explicit, reviewable steps.
    if value is None:
        return None
    document = _object(value, "settlement requirement")
    _keys(
        document,
        # Open the initial delay transactions and maximum followup delay transactions
        # payload explicitly for _keys within settlement requirement.
        {
            "initial_delay_transactions",
            "maximum_followup_delay_transactions",
            "maximum_tail_blocks",
            "minimum_duration_ns",
            # Pass schema explicitly so _keys receives a reviewable initial delay
            # transactions and maximum followup delay transactions input in settlement
            # requirement.
            "schema",
            "settlement_streams",
            "target_stream",
        },
        "settlement requirement",
        # Complete _keys only after its initial delay transactions and maximum followup delay
        # transactions inputs are visible in settlement requirement.
    )
    return SettlementRequirement(
        schema=_string(document["schema"], "settlement requirement schema"),
        target_stream=CapabilityStream(
            _string(document["target_stream"], "settlement target stream")
            # Complete CapabilityStream only after its settlement target stream and target
            # stream inputs are visible in settlement requirement.
        ),
        settlement_streams=tuple(
            CapabilityStream(item)
            for item in _strings(
                document["settlement_streams"],
                # Pass settlement streams explicitly so _strings receives a reviewable
                # settlement streams and document input in settlement requirement.
                "settlement streams",
            )
        ),
        initial_delay_transactions=_integer(
            document["initial_delay_transactions"],
            # Pass initial delay transactions explicitly so _integer receives a reviewable
            # initial delay transactions and document input in settlement requirement.
            "initial_delay_transactions",
            minimum=1,
        ),
        minimum_duration_ns=_integer(
            document["minimum_duration_ns"],
            # Pass minimum duration ns explicitly so _integer receives a reviewable
            # minimum duration ns and document input in settlement requirement.
            "minimum_duration_ns",
            minimum=1,
        ),
        maximum_followup_delay_transactions=_integer(
            document["maximum_followup_delay_transactions"],
            # Pass maximum followup delay transactions explicitly so _integer receives a
            # reviewable maximum followup delay transactions and document input in
            # settlement requirement.
            "maximum_followup_delay_transactions",
            minimum=1,
        ),
        maximum_tail_blocks=_integer(
            document["maximum_tail_blocks"],
            # Pass maximum tail blocks explicitly so _integer receives a reviewable
            # maximum tail blocks and document input in settlement requirement.
            "maximum_tail_blocks",
            minimum=1,
        ),
    )


def _capability_document(item: PlannedCapability) -> dict[str, object]:
    # Execute the capability document workflow in explicit, reviewable steps.
    return {
        "capability_id": item.capability_id.value,
        "columns": list(item.columns),
        "fidelity": {
            "chain_finality": item.fidelity.chain_finality.value,
            # Include completeness in the completed capability document result.
            "completeness": item.fidelity.completeness.value,
            "consistency": item.fidelity.consistency.value,
            "fees": item.fidelity.fees.value,
            "identity": item.fidelity.identity.value,
            "ordering": item.fidelity.ordering.value,
            # Include state in the completed capability document result.
            "state": item.fidelity.state.value,
        },
        "keyset_key_is_proven": item.keyset_key_is_proven,
        "protocol": item.protocol,
        "protocol_version": item.protocol_version,
        # Include proofs in the completed capability document result.
        "proofs": _proofs_document(item.proofs),
        "schema_version": item.schema_version,
        "stream": item.stream.value,
        "total_key": list(item.total_key),
        "utc_pruning_column": item.utc_pruning_column,
        # Include utc pruning is proven in the completed capability document result.
        "utc_pruning_is_proven": item.utc_pruning_is_proven,
    }


def _proofs_document(value: CapabilityProofs) -> dict[str, str]:
    return {field_name: getattr(value, field_name).value for field_name in CAPABILITY_PROOF_FIELDS}


def _proofs(value: object) -> CapabilityProofs:
    # Execute the proofs workflow in explicit, reviewable steps.
    document = _object(value, "capability proofs")
    _keys(document, set(CAPABILITY_PROOF_FIELDS), "capability proofs")
    return CapabilityProofs(
        **{
            field_name: EvidenceStatus(_string(document[field_name], field_name))
            # Pass field name explicitly so CapabilityProofs receives a reviewable
            # evidence status and string input in proofs.
            for field_name in CAPABILITY_PROOF_FIELDS
        }
    )


def _capability(value: object) -> PlannedCapability:
    # Execute the capability workflow in explicit, reviewable steps.
    document = _object(value, "planned capability")
    _keys(
        document,
        {
            "capability_id",
            # Pass columns explicitly so _keys receives a reviewable capability id and
            # columns input in capability.
            "columns",
            "fidelity",
            "keyset_key_is_proven",
            "protocol",
            "protocol_version",
            # Pass proofs explicitly so _keys receives a reviewable capability id and
            # columns input in capability.
            "proofs",
            "schema_version",
            "stream",
            "total_key",
            "utc_pruning_column",
            # Pass utc pruning is proven explicitly so _keys receives a reviewable
            # capability id and columns input in capability.
            "utc_pruning_is_proven",
        },
        "planned capability",
    )
    fidelity = _object(document["fidelity"], "source fidelity")
    # Invoke _keys for chain finality and completeness as a visible capability step.
    _keys(
        fidelity,
        {
            "chain_finality",
            "completeness",
            # Pass consistency explicitly so _keys receives a reviewable chain finality
            # and completeness input in capability.
            "consistency",
            "fees",
            "identity",
            "ordering",
            "state",
            # Close the chain finality and completeness payload only after all capability
            # fields are present.
        },
        "source fidelity",
    )
    return PlannedCapability(
        capability_id=CapabilityId(_string(document["capability_id"], "capability_id")),
        # Include protocol in the completed capability result.
        protocol=_string(document["protocol"], "protocol"),
        protocol_version=_string(document["protocol_version"], "protocol_version"),
        schema_version=_string(document["schema_version"], "schema_version"),
        stream=CapabilityStream(_string(document["stream"], "stream")),
        columns=_strings(document["columns"], "columns"),
        # Include fidelity in the completed capability result.
        fidelity=SourceFidelity(
            identity=IdentityFidelity(_string(fidelity["identity"], "identity fidelity")),
            ordering=OrderingFidelity(_string(fidelity["ordering"], "ordering fidelity")),
            state=StateFidelity(_string(fidelity["state"], "state fidelity")),
            fees=FeesFidelity(_string(fidelity["fees"], "fees fidelity")),
            # Include chain finality in the completed capability result.
            chain_finality=ChainFinality(_string(fidelity["chain_finality"], "chain finality")),
            completeness=IngestionCompleteness(_string(fidelity["completeness"], "completeness")),
            consistency=SourceConsistency(_string(fidelity["consistency"], "consistency")),
        ),
        proofs=_proofs(document["proofs"]),
        # Include total key in the completed capability result.
        total_key=_strings(document["total_key"], "total_key"),
        keyset_key_is_proven=_boolean(document["keyset_key_is_proven"], "keyset_key_is_proven"),
        utc_pruning_column=_optional_string(document["utc_pruning_column"], "utc_pruning_column"),
        utc_pruning_is_proven=_boolean(document["utc_pruning_is_proven"], "utc_pruning_is_proven"),
    )


# Define evidence document as one focused operation with an explicit boundary.
def _evidence_document(item: CapabilityCutEvidence) -> dict[str, object]:
    # Execute the evidence document workflow in explicit, reviewable steps.
    return {
        "block_range": _range_document(item.block_range),
        "capability_id": item.capability_id.value,
        "chain_finality": item.chain_finality.value,
        "completeness": item.completeness.value,
        # Include consistency in the completed evidence document result.
        "consistency": item.consistency.value,
        "ingestion_watermark_to_block": item.ingestion_watermark_to_block,
        "snapshot_cut_to_block": item.snapshot_cut_to_block,
        "upstream_revision": item.upstream_revision,
    }


# Define evidence as one focused operation with an explicit boundary.
def _evidence(value: object) -> CapabilityCutEvidence:
    # Execute the evidence workflow in explicit, reviewable steps.
    document = _object(value, "cut evidence")
    _keys(
        document,
        {
            "capability_id",
            # Pass chain finality explicitly so _keys receives a reviewable capability id
            # and chain finality input in evidence.
            "chain_finality",
            "completeness",
            "consistency",
            "block_range",
            "ingestion_watermark_to_block",
            # Pass snapshot cut to block explicitly so _keys receives a reviewable
            # capability id and chain finality input in evidence.
            "snapshot_cut_to_block",
            "upstream_revision",
        },
        "cut evidence",
    )
    # Return the completed evidence result without a hidden fallback.
    return CapabilityCutEvidence(
        capability_id=CapabilityId(_string(document["capability_id"], "capability_id")),
        block_range=_range(document["block_range"], "block_range"),
        snapshot_cut_to_block=_integer(document["snapshot_cut_to_block"], "snapshot_cut_to_block"),
        chain_finality=ChainFinality(_string(document["chain_finality"], "chain_finality")),
        # Include ingestion watermark to block in the completed evidence result.
        ingestion_watermark_to_block=_optional_integer(
            document["ingestion_watermark_to_block"], "ingestion_watermark_to_block"
        ),
        completeness=IngestionCompleteness(_string(document["completeness"], "completeness")),
        consistency=SourceConsistency(_string(document["consistency"], "consistency")),
        # Include upstream revision in the completed evidence result.
        upstream_revision=_optional_string(document["upstream_revision"], "upstream_revision"),
    )


def _shard(value: object) -> DatasetShard:
    # Execute the shard workflow in explicit, reviewable steps.
    document = _object(value, "dataset shard")
    _keys(
        document,
        {"block_range", "capability_id", "columns", "ordinal"},
        "dataset shard",
        # Complete _keys only after its block range and capability id inputs are visible in
        # shard.
    )
    return DatasetShard(
        ordinal=_integer(document["ordinal"], "ordinal"),
        capability_id=CapabilityId(_string(document["capability_id"], "capability_id")),
        block_range=_range(document["block_range"], "block_range"),
        # Include columns in the completed shard result.
        columns=_strings(document["columns"], "columns"),
    )


def _capability_range(value: object) -> CapabilityExtractionRange:
    # Execute the capability range workflow in explicit, reviewable steps.
    document = _object(value, "capability extraction range")
    _keys(document, {"block_range", "capability_id"}, "capability extraction range")
    return CapabilityExtractionRange(
        capability_id=CapabilityId(_string(document["capability_id"], "capability_id")),
        block_range=_range(document["block_range"], "block_range"),
        # Complete CapabilityExtractionRange only after its capability id and block range
        # inputs are visible in capability range.
    )


def _budget(value: object) -> BudgetReport:
    # Execute the budget workflow in explicit, reviewable steps.
    document = _object(value, "budget")
    fields = {
        "current_free_disk_bytes",
        "disk_low_watermark_bytes",
        "estimated_source_bytes",
        # Keep the estimated source rows component named inside the fields contract.
        "estimated_source_rows",
        "expected_local_parquet_bytes",
        "issues",
        "max_days",
        "max_local_bytes",
        # Keep the max remote bytes component named inside the fields contract.
        "max_remote_bytes",
        "max_shard_blocks",
        "max_total_shards",
        "max_total_blocks",
        "planned_shards",
        # Keep the requested days component named inside the fields contract.
        "requested_days",
        "requested_blocks",
        "status",
        "temporary_reserve_bytes",
    }
    # Invoke _keys for budget and document as a visible budget step.
    _keys(document, fields, "budget")
    return BudgetReport(
        status=BudgetStatus(_string(document["status"], "budget status")),
        estimated_source_rows=_optional_integer(
            document["estimated_source_rows"],
            # Pass estimated source rows explicitly so _optional_integer receives a
            # reviewable estimated source rows and document input in budget.
            "estimated_source_rows",
            # Complete _optional_integer only after its estimated source rows and document
            # inputs are visible in budget.
        ),
        estimated_source_bytes=_optional_integer(
            document["estimated_source_bytes"], "estimated_source_bytes"
        ),
        requested_days=_optional_integer(document["requested_days"], "requested_days"),
        # Include requested blocks in the completed budget result.
        requested_blocks=_integer(document["requested_blocks"], "requested_blocks"),
        planned_shards=_integer(document["planned_shards"], "planned_shards"),
        expected_local_parquet_bytes=_optional_integer(
            document["expected_local_parquet_bytes"], "expected_local_parquet_bytes"
        ),
        # Include temporary reserve bytes in the completed budget result.
        temporary_reserve_bytes=_optional_integer(
            document["temporary_reserve_bytes"], "temporary_reserve_bytes"
        ),
        current_free_disk_bytes=_optional_integer(
            document["current_free_disk_bytes"],
            # Pass current free disk bytes explicitly so _optional_integer receives a
            # reviewable current free disk bytes and document input in budget.
            "current_free_disk_bytes",
            # Complete _optional_integer only after its current free disk bytes and document
            # inputs are visible in budget.
        ),
        disk_low_watermark_bytes=_integer(
            document["disk_low_watermark_bytes"], "disk_low_watermark_bytes"
        ),
        max_remote_bytes=_integer(document["max_remote_bytes"], "max_remote_bytes"),
        # Include max local bytes in the completed budget result.
        max_local_bytes=_integer(document["max_local_bytes"], "max_local_bytes"),
        max_days=_integer(document["max_days"], "max_days"),
        max_total_blocks=_integer(document["max_total_blocks"], "max_total_blocks"),
        max_total_shards=_integer(document["max_total_shards"], "max_total_shards"),
        max_shard_blocks=_integer(document["max_shard_blocks"], "max_shard_blocks"),
        # Include issues in the completed budget result.
        issues=tuple(_issue(item) for item in _list(document["issues"], "issues")),
    )


def _issue(value: object) -> BudgetIssue:
    # Execute the issue workflow in explicit, reviewable steps.
    document = _object(value, "budget issue")
    _keys(document, {"actual", "code", "kind", "limit", "message"}, "budget issue")
    return BudgetIssue(
        code=_string(document["code"], "issue code"),
        kind=BudgetIssueKind(_string(document["kind"], "issue kind")),
        # Include message in the completed issue result.
        message=_string(document["message"], "issue message"),
        actual=_optional_integer(document["actual"], "issue actual"),
        limit=_optional_integer(document["limit"], "issue limit"),
    )


def _query_limits(value: object) -> QueryLimits:
    # Execute the query limits workflow in explicit, reviewable steps.
    document = _object(value, "query limits")
    _keys(
        document,
        {"max_execution_seconds", "max_memory_bytes", "max_result_rows"},
        "query limits",
        # Complete _keys only after its max execution seconds and max memory bytes inputs are
        # visible in query limits.
    )
    return QueryLimits(
        max_execution_seconds=_integer(
            document["max_execution_seconds"], "max_execution_seconds", minimum=1
        ),
        # Include max memory bytes in the completed query limits result.
        max_memory_bytes=_integer(document["max_memory_bytes"], "max_memory_bytes", minimum=1),
        max_result_rows=_optional_integer(document["max_result_rows"], "max_result_rows"),
    )


def _range_document(value: BlockRange) -> dict[str, int | str]:
    # Execute the range document workflow in explicit, reviewable steps.
    return {
        "from_block_ordinal": value.from_block_ordinal,
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "to_block_ordinal": value.to_block_ordinal,
        # Return the completed range document result without a hidden fallback.
    }


def _range(value: object, field: str) -> BlockRange:
    # Execute the range workflow in explicit, reviewable steps.
    document = _object(value, field)
    _keys(
        document,
        {
            "from_block_ordinal",
            # Pass network id explicitly so _keys receives a reviewable from block ordinal
            # and network id input in range.
            "network_id",
            "position_schema_id",
            "to_block_ordinal",
        },
        field,
        # Complete _keys only after its from block ordinal and network id inputs are visible
        # in range.
    )
    return BlockRange(
        NetworkId(_string(document["network_id"], f"{field}.network_id")),
        PositionSchemaId(_string(document["position_schema_id"], f"{field}.position_schema_id")),
        _integer(document["from_block_ordinal"], f"{field}.from_block_ordinal"),
        # Include integer in the completed range result.
        _integer(document["to_block_ordinal"], f"{field}.to_block_ordinal"),
    )


def _optional_range(value: object, field: str) -> BlockRange | None:
    return None if value is None else _range(value, field)


def _object(value: object, field: str) -> dict[str, object]:
    # Execute the object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DatasetPlanCodecError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], field: str) -> None:
    # Execute the keys workflow in explicit, reviewable steps.
    if set(value) != expected:
        raise DatasetPlanCodecError(f"{field} schema is invalid")


def _list(value: object, field: str) -> list[object]:
    # Execute the list workflow in explicit, reviewable steps.
    if not isinstance(value, list):
        raise DatasetPlanCodecError(f"{field} must be a list")
    return cast(list[object], value)


def _string(value: object, field: str) -> str:
    # Execute the string workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise DatasetPlanCodecError(f"{field} must be a non-empty trimmed string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    return None if value is None else _string(value, field)


# Define strings as one focused operation with an explicit boundary.
def _strings(value: object, field: str) -> tuple[str, ...]:
    return tuple(_string(item, field) for item in _list(value, field))


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    # Execute the integer workflow in explicit, reviewable steps.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DatasetPlanCodecError(f"{field} must be an integer >= {minimum}")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    return None if value is None else _integer(value, field)


# Define boolean as one focused operation with an explicit boundary.
def _boolean(value: object, field: str) -> bool:
    # Execute the boolean workflow in explicit, reviewable steps.
    if not isinstance(value, bool):
        raise DatasetPlanCodecError(f"{field} must be a boolean")
    return value


__all__ = [
    "DatasetPlanCodecError",
    # Keep the dataset plan bytes component named inside the all contract.
    "dataset_plan_bytes",
    "dataset_plan_from_bytes",
    "dataset_spec_document",
    "dataset_spec_from_document",
]
