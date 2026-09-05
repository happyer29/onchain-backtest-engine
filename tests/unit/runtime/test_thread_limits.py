# Declare this module's dependencies and contracts before execution.
import pytest

from backtest.runtime.thread_limits import (
    ChildProcessEnvironmentError,
    apply_child_process_determinism,
    apply_thread_limits,
    # Include require child process determinism so the thread limits dependency remains
    # explicit.
    require_child_process_determinism,
)


def test_thread_limits_update_only_supplied_environment() -> None:
    # Execute the test thread limits update only supplied environment workflow in
    # explicit, reviewable steps.
    environ: dict[str, str] = {}

    changed = apply_thread_limits(2, environ)

    assert changed
    assert set(changed.values()) == {"2"}
    assert environ == changed


# Define test declared child environment includes hash seed and all thread limits as one
# focused operation with an explicit boundary.
def test_declared_child_environment_includes_hash_seed_and_all_thread_limits() -> None:
    # Execute the test declared child environment includes hash seed and all thread limits
    # workflow in explicit, reviewable steps.
    environ = {"UNRELATED": "preserved", "PYTHONHASHSEED": "wrong"}

    changed = apply_child_process_determinism(3, environ)

    assert changed["PYTHONHASHSEED"] == "0"
    assert set(changed.values()) == {"0", "3"}
    assert environ == {"UNRELATED": "preserved", **changed}
    # Invoke require_child_process_determinism for environ as a visible test declared
    # child environment includes hash seed and all thread limits step.
    require_child_process_determinism(3, environ)


def test_child_environment_mismatch_fails_closed() -> None:
    # Execute the test child environment mismatch fails closed workflow in explicit,
    # reviewable steps.
    environ: dict[str, str] = {}
    apply_child_process_determinism(1, environ)
    environ["PYTHONHASHSEED"] = "different"

    with pytest.raises(ChildProcessEnvironmentError, match="runtime contract"):
        require_child_process_determinism(1, environ)
