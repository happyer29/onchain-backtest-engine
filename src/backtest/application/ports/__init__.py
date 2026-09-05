"""Outbound hexagonal ports exposed by the application layer."""

from backtest.application.ports.artifacts import (
    ArtifactHandle,
    ArtifactRepository,
    ArtifactWriter,
)

# Import canonical at the visible module dependency boundary.
from backtest.application.ports.canonical import CanonicalSnapshotStore
from backtest.application.ports.catalog import ArtifactCatalog, RunMetadataIndex
from backtest.application.ports.jobs import JobCompletionQueue, JobQuery, JobQueue
from backtest.application.ports.models import ModelRepository
from backtest.application.ports.processes import (
    # Include process identity error so the processes dependency remains explicit.
    ProcessIdentityError,
    ProcessRunner,
    ProcessRunnerError,
    ProcessSpawnError,
)

# Import progress at the visible module dependency boundary.
from backtest.application.ports.progress import ProgressSink
from backtest.application.ports.projectors import ProtocolProjector
from backtest.application.ports.replay import BoundaryReader, EventBatch, ReplaySource
from backtest.application.ports.source import (
    CapabilityProvider,
    # Include dataset estimator so the source dependency remains explicit.
    DatasetEstimator,
    DiskCapacityProbe,
    IndexedBatch,
    SourceMetadataReader,
    SourceReader,
    # Close the source import after its required symbols are visible.
)
from backtest.application.ports.strategies import (
    EventView,
    Intent,
    Strategy,
    # Include strategy context so the strategies dependency remains explicit.
    StrategyContext,
)
from backtest.application.ports.supervisor import (
    AdmissionController,
    ControllerAuthority,
    # Include supervisor clock so the supervisor dependency remains explicit.
    SupervisorClock,
    SupervisorJobQueue,
    SupervisorQueue,
)

__all__ = [
    # Keep the admission controller component named inside the all contract.
    "AdmissionController",
    "ArtifactCatalog",
    "ArtifactHandle",
    "ArtifactRepository",
    "ArtifactWriter",
    # Keep the boundary reader component named inside the all contract.
    "BoundaryReader",
    "CanonicalSnapshotStore",
    "CapabilityProvider",
    "ControllerAuthority",
    "DatasetEstimator",
    # Keep the disk capacity probe component named inside the all contract.
    "DiskCapacityProbe",
    "EventBatch",
    "EventView",
    "IndexedBatch",
    "Intent",
    # Keep the job completion queue component named inside the all contract.
    "JobCompletionQueue",
    "JobQuery",
    "JobQueue",
    "ModelRepository",
    "ProcessIdentityError",
    # Keep the process runner component named inside the all contract.
    "ProcessRunner",
    "ProcessRunnerError",
    "ProcessSpawnError",
    "ProgressSink",
    "ProtocolProjector",
    # Keep the replay source component named inside the all contract.
    "ReplaySource",
    "RunMetadataIndex",
    "SourceMetadataReader",
    "SourceReader",
    "Strategy",
    "StrategyContext",
    # Keep the supervisor clock component named inside the all contract.
    "SupervisorClock",
    "SupervisorJobQueue",
    "SupervisorQueue",
]
