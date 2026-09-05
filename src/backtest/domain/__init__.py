"""Pure domain contracts shared by the backtesting application."""

from backtest.domain.chain import (
    BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
    SOLANA_MAINNET_NETWORK_ID,
    ChainIdentityMismatchError,
    ChainPosition,
    # Include unsupported position schema error so the chain dependency remains explicit.
    UnsupportedPositionSchemaError,
    boundary_coordinates,
    boundary_ordinal,
)
from backtest.domain.fidelity import (
    # Include chain finality so the fidelity dependency remains explicit.
    ChainFinality,
    FeesFidelity,
    FidelityGap,
    FidelityRequirement,
    IdentityFidelity,
    # Include ingestion completeness so the fidelity dependency remains explicit.
    IngestionCompleteness,
    OrderingFidelity,
    SourceConsistency,
    SourceFidelity,
    StateFidelity,
    # Close the fidelity import after its required symbols are visible.
)
from backtest.domain.identifiers import (
    AccountId,
    ArtifactId,
    AssetId,
    # Include attempt id so the identifiers dependency remains explicit.
    AttemptId,
    BundleId,
    CapabilityId,
    ContentDigest,
    DatasetRevisionId,
    # Include delivery schedule id so the identifiers dependency remains explicit.
    DeliveryScheduleId,
    ExecutionAttemptId,
    FeatureSetId,
    FeeComponentId,
    JobId,
    # Include logical content hash so the identifiers dependency remains explicit.
    LogicalContentHash,
    LogicalRunId,
    ModelBundleId,
    NetworkId,
    OrderId,
    # Include pool id so the identifiers dependency remains explicit.
    PoolId,
    PositionSchemaId,
    PredictionSetId,
    ProtocolPayloadSchemaId,
    ReplayPackId,
    # Include runtime lock id so the identifiers dependency remains explicit.
    RuntimeLockId,
    SnapshotId,
    SourceId,
    VenueId,
)

# Import time at the visible module dependency boundary.
from backtest.domain.time import BlockRange, SlotRange

__all__ = [
    "BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID",
    "SOLANA_MAINNET_NETWORK_ID",
    "AccountId",
    # Keep the artifact id component named inside the all contract.
    "ArtifactId",
    "AssetId",
    "AttemptId",
    "BlockRange",
    "BundleId",
    # Keep the capability id component named inside the all contract.
    "CapabilityId",
    "ChainFinality",
    "ChainIdentityMismatchError",
    "ChainPosition",
    "ContentDigest",
    # Keep the dataset revision id component named inside the all contract.
    "DatasetRevisionId",
    "DeliveryScheduleId",
    "ExecutionAttemptId",
    "FeatureSetId",
    "FeeComponentId",
    # Keep the fees fidelity component named inside the all contract.
    "FeesFidelity",
    "FidelityGap",
    "FidelityRequirement",
    "IdentityFidelity",
    "IngestionCompleteness",
    # Keep the job id component named inside the all contract.
    "JobId",
    "LogicalContentHash",
    "LogicalRunId",
    "ModelBundleId",
    "NetworkId",
    # Keep the order id component named inside the all contract.
    "OrderId",
    "OrderingFidelity",
    "PoolId",
    "PositionSchemaId",
    "PredictionSetId",
    # Keep the protocol payload schema id component named inside the all contract.
    "ProtocolPayloadSchemaId",
    "ReplayPackId",
    "RuntimeLockId",
    "SlotRange",
    "SnapshotId",
    # Keep the source consistency component named inside the all contract.
    "SourceConsistency",
    "SourceFidelity",
    "SourceId",
    "StateFidelity",
    "UnsupportedPositionSchemaError",
    # Keep the venue id component named inside the all contract.
    "VenueId",
    "boundary_coordinates",
    "boundary_ordinal",
]
