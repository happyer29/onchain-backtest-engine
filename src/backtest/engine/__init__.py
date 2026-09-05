"""Deterministic simulation core.

The causal scheduler is intentionally introduced with the vertical backtest
slice. Source access and infrastructure dependencies must never be added here.
"""

from backtest.engine.reference import (
    ENGINE_BUNDLE_ID,
    SLOT_LATENCY_MODEL_BUNDLE_ID,
    EngineInvariantError,
    ReferenceBacktestEngine,
    # Include reference run config so the reference dependency remains explicit.
    ReferenceRunConfig,
    RunSummary,
    SlotLatencyModel,
)
from backtest.engine.sniping import (
    # Include sniping reference backend name so the sniping dependency remains explicit.
    SNIPING_REFERENCE_BACKEND_NAME,
    SNIPING_REFERENCE_ENGINE_BUNDLE_ID,
    NullSnipingRunEventSink,
    SnipingEngineError,
    SnipingEngineErrorCode,
    # Include sniping reference engine so the sniping dependency remains explicit.
    SnipingReferenceEngine,
    SnipingRunConfig,
    SnipingRunSummary,
)
from backtest.engine.transaction_clock import (
    # Include compact transaction clock so the transaction clock dependency remains
    # explicit.
    CompactTransactionClock,
    TransactionClockError,
    TransactionClockErrorCode,
)

__all__ = [
    # Keep the engine bundle id component named inside the all contract.
    "ENGINE_BUNDLE_ID",
    "SLOT_LATENCY_MODEL_BUNDLE_ID",
    "SNIPING_REFERENCE_BACKEND_NAME",
    "SNIPING_REFERENCE_ENGINE_BUNDLE_ID",
    "CompactTransactionClock",
    # Keep the engine invariant error component named inside the all contract.
    "EngineInvariantError",
    "NullSnipingRunEventSink",
    "ReferenceBacktestEngine",
    "ReferenceRunConfig",
    "RunSummary",
    # Keep the slot latency model component named inside the all contract.
    "SlotLatencyModel",
    "SnipingEngineError",
    "SnipingEngineErrorCode",
    "SnipingReferenceEngine",
    "SnipingRunConfig",
    # Keep the sniping run summary component named inside the all contract.
    "SnipingRunSummary",
    "TransactionClockError",
    "TransactionClockErrorCode",
]
