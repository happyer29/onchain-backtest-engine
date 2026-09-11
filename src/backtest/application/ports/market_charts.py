"""Replaceable bounded history reader used only for post-run result inspection."""

from typing import Protocol

from backtest.application.market_charts import CopyMarketChart, StrategyMarketChart
from backtest.application.run_results import SuccessfulRunManifest

# A selector names an already verified result row, never an arbitrary source mint.
from backtest.domain.identifiers import ArtifactId
from backtest.domain.roundtrips import RoundTripRecord
from backtest.engine.copytrading_results import CopyPositionRecord


class CopyMarketChartReader(Protocol):
    """Project retained canonical history without running a strategy or changing artifacts."""

    def read(
        self,
        artifact_id: ArtifactId,
        manifest: SuccessfulRunManifest,
        position: CopyPositionRecord,
        # The implementation must reject missing history and hard-limit violations.
    ) -> CopyMarketChart: ...


class StrategyMarketChartReader(Protocol):
    """Common history projection for verified creation and copy-trade signals."""

    def read(
        self,
        artifact_id: ArtifactId,
        manifest: SuccessfulRunManifest,
        position: CopyPositionRecord | RoundTripRecord,
    ) -> StrategyMarketChart: ...
