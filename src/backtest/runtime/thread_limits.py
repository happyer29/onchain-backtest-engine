"""Native thread-pool limits applied before importing numerical libraries."""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping

_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    # Keep the mkl num threads component named inside the thread env vars contract.
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "ARROW_NUM_THREADS",
    # Keep the backtest duckdb threads component named inside the thread env vars
    # contract.
    "BACKTEST_DUCKDB_THREADS",
    "BACKTEST_ONNX_INTRA_OP_THREADS",
)
_CHILD_HASH_SEED = "0"


class ChildProcessEnvironmentError(RuntimeError):
    """The current process does not match the declared child runtime."""


def apply_thread_limits(
    threads: int,
    environ: MutableMapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Set deterministic native-library limits and return changed values."""

    if threads <= 0:
        raise ValueError("threads must be positive")
    target = os.environ if environ is None else environ
    value = str(threads)
    changed: dict[str, str] = {}
    # Traverse _THREAD_ENV_VARS explicitly so each apply thread limits iteration remains
    # traceable.
    for name in _THREAD_ENV_VARS:
        # Process _THREAD_ENV_VARS inside the bounded apply thread limits loop.
        target[name] = value
        changed[name] = value
    target["BACKTEST_ONNX_INTER_OP_THREADS"] = value
    changed["BACKTEST_ONNX_INTER_OP_THREADS"] = value
    return changed


# Define apply child process determinism as one focused operation with an explicit
# boundary.
def apply_child_process_determinism(
    threads: int,
    environ: MutableMapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Materialize the one declared environment for isolated job children."""

    target = os.environ if environ is None else environ
    changed = dict(apply_thread_limits(threads, target))
    target["PYTHONHASHSEED"] = _CHILD_HASH_SEED
    changed["PYTHONHASHSEED"] = _CHILD_HASH_SEED
    return changed


# Define require child process determinism as one focused operation with an explicit
# boundary.
def require_child_process_determinism(
    threads: int,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Fail closed unless this interpreter inherited the declared child env."""

    actual = os.environ if environ is None else environ
    expected = dict(actual)
    declared = apply_child_process_determinism(threads, expected)
    if any(actual.get(name) != value for name, value in declared.items()):
        # Handle the require child process determinism value, get and name condition as a
        # distinct block.
        raise ChildProcessEnvironmentError(
            "isolated child environment differs from its deterministic runtime contract"
        )


__all__ = [
    "ChildProcessEnvironmentError",
    # Keep the apply child process determinism component named inside the all contract.
    "apply_child_process_determinism",
    "apply_thread_limits",
    "require_child_process_determinism",
]
