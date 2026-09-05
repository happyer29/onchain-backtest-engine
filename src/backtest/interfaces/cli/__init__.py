"""Typer command-line interface."""

from backtest.interfaces.cli.main import (
    CliBackend,
    CliBackendFactory,
    CliRecoveryBackend,
    CliRecoveryBackendFactory,
    # Include cli usage error so the main dependency remains explicit.
    CliUsageError,
    create_cli,
)

__all__ = [
    "CliBackend",
    # Keep the cli backend factory component named inside the all contract.
    "CliBackendFactory",
    "CliRecoveryBackend",
    "CliRecoveryBackendFactory",
    "CliUsageError",
    "create_cli",
    # Complete the all group only after its semantic components are visible.
]
