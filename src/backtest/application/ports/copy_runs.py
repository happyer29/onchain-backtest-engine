"""Replaceable exact component seam for reference copy-buy execution."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# Concrete factories are wired only by bootstrap and satisfy core-owned interfaces.
from backtest.application.ports.runs import RuntimeComponentReceipt
from backtest.application.run_specs import ResolvedRunSpec
from backtest.engine.copytrading_contracts import CopyBuyProtocolRuntime, CopyBuyStrategy
from backtest.engine.copytrading_run import CopyRunConfig
from backtest.engine.sniping_contracts import SnipingNetworkCostModel


@dataclass(frozen=True, slots=True)
class ResolvedCopyRuntime:
    """Fresh strategy/account state and exact code/config receipts for one run."""

    strategy: CopyBuyStrategy
    protocol_factory: Callable[[], CopyBuyProtocolRuntime]
    network_costs: SnipingNetworkCostModel
    config: CopyRunConfig
    receipts: tuple[RuntimeComponentReceipt, ...]


class CopyRuntimeResolver(Protocol):
    """Instantiate installed code only after verifying the complete immutable closure."""

    def resolve(self, spec: ResolvedRunSpec) -> ResolvedCopyRuntime: ...
