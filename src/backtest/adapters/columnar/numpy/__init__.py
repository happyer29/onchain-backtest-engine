"""Deterministic NumPy mmap ReplayPack compiler and reader."""

from backtest.adapters.columnar.numpy.compiler import (
    LocalNumpyReplayPackCompiler,
    ReplayPackCompileError,
)
from backtest.adapters.columnar.numpy.layout import (
    # Include compiler version so the layout dependency remains explicit.
    COMPILER_VERSION as NUMPY_REPLAY_COMPILER_VERSION,
)
from backtest.adapters.columnar.numpy.optimized_engine import (
    NUMPY_MMAP_FIRST_SWAP_BACKEND,
    NumpyMmapFirstSwapEngine,
    # Include optimized backend unsupported so the optimized engine dependency remains
    # explicit.
    OptimizedBackendUnsupported,
)
from backtest.adapters.columnar.numpy.reader import NumpyMmapReplaySource, ReplayPackFormatError
from backtest.adapters.columnar.numpy.sniping_engine import (
    NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND,
    # Include numpy mmap pumpfun sniping engine so the sniping engine dependency remains
    # explicit.
    NumpyMmapPumpfunSnipingEngine,
    OptimizedSnipingBackendUnsupported,
)

__all__ = [
    "NUMPY_MMAP_FIRST_SWAP_BACKEND",
    # Keep the numpy mmap pumpfun sniping backend component named inside the all contract.
    "NUMPY_MMAP_PUMPFUN_SNIPING_BACKEND",
    "NUMPY_REPLAY_COMPILER_VERSION",
    "LocalNumpyReplayPackCompiler",
    "NumpyMmapFirstSwapEngine",
    "NumpyMmapPumpfunSnipingEngine",
    # Keep the numpy mmap replay source component named inside the all contract.
    "NumpyMmapReplaySource",
    "OptimizedBackendUnsupported",
    "OptimizedSnipingBackendUnsupported",
    "ReplayPackCompileError",
    "ReplayPackFormatError",
    # Complete the all group only after its semantic components are visible.
]
