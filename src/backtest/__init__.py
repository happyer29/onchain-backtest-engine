"""On-Chain Backtest Engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("on-chain-backtest-engine")
except PackageNotFoundError:  # pragma: no cover - editable source without install
    __version__ = "0+unknown"

__all__ = ["__version__"]
