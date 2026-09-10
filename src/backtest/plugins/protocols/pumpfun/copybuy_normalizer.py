"""Signer-preserving source transform using the existing exact Pump validators."""

from __future__ import annotations

from backtest.application.models import CapabilityStream
from backtest.domain.hashing import domain_digest
from backtest.domain.identifiers import CapabilityId, ContentDigest
from backtest.domain.time import BlockRange

# Copy launch classification has a distinct version from creation-triggered Sniping.
from backtest.plugins.protocols.pumpfun.copybuy_payload import COPYBUY_UNIVERSE_POLICY_ID

# Reuse reserve, fee, skipped-slot and terminal-lifecycle semantics unchanged.
from backtest.plugins.protocols.pumpfun.live_normalizer import (
    PumpfunLiveNormalizer,
    PumpfunNormalizationObservationSink,
    PumpfunNormalizationSession,
    _public_key,
    # Raw row access remains internal to source normalization.
    _Row,
)


class PumpfunCopyBuyLiveNormalizer(PumpfunLiveNormalizer):
    """A separate source profile; legacy normalized bytes retain their meaning."""

    __slots__ = ()

    @property
    def profile_id(self) -> str:
        """Pin the actor-preserving transform independently of Sniping."""
        return "pumpfun-copybuy-live-normalizer/v1"

    @property
    def launch_universe_policy_id(self) -> str:
        """Creation classification is required for all candidate leader purchases."""
        return COPYBUY_UNIVERSE_POLICY_ID

    @property
    def config_digest(self) -> ContentDigest:
        """Commit both shared integer transforms and the additional actor schema."""
        document: dict[str, object] = {
            "base_transform_digest": super().config_digest.hex,
            "profile_id": self.profile_id,
            "universe_policy_id": self.launch_universe_policy_id,
        }
        # Output columns affect content even when a particular shard has zero rows.
        document["trade_columns"] = list(self.output_columns(CapabilityStream.PUMP_CURVE_TRADE))
        return domain_digest("backtest.pumpfun-copybuy-normalizer.v1", document)

    def output_columns(self, stream: CapabilityStream) -> tuple[str, ...]:
        """Never infer an actor from creator, fee payer or transaction grouping."""
        columns = super().output_columns(stream)
        if stream is CapabilityStream.PUMP_CURVE_TRADE:
            return (*columns, "signing_wallet")
        return columns

    def begin(
        self,
        *,
        stream: CapabilityStream,
        capability_id: CapabilityId,
        # Each session proves one explicit shard and preserves normalization observations.
        covered_range: BlockRange,
        observation_sink: PumpfunNormalizationObservationSink | None = None,
    ) -> PumpfunNormalizationSession:
        """Retain streaming failure, digest and ordering behavior of the exact source."""
        return _CopyBuyNormalizationSession(
            normalizer=self,
            stream=stream,
            capability_id=capability_id,
            covered_range=covered_range,
            # The observation sink carries source proof provenance outside the canonical event
            # stream.
            observation_sink=observation_sink,
        )


class _CopyBuyNormalizationSession(PumpfunNormalizationSession):
    """Validate the signer before accepting the existing exact trade transform."""

    __slots__ = ()

    def _normalize_trade(self, values: _Row) -> tuple[object, ...]:
        """Missing or malformed source actors poison the entire shard."""
        signer = _public_key(values["signing_wallet"])
        return (*super()._normalize_trade(values), signer)
