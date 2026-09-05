"""Stateless keyed random draws that are independent of batching/order."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256

from backtest.domain.identifiers import ContentDigest

# Bind rng algorithm once as an explicit module-level contract.
RNG_ALGORITHM = "hmac-sha256-keyed-v1"


# Keep the keyed rng contract and validation rules together.
@dataclass(frozen=True, slots=True)
class KeyedRng:
    root_seed: int

    def __post_init__(self) -> None:
        # Execute the keyed rng post init workflow in explicit, reviewable steps.
        if (
            isinstance(self.root_seed, bool)
            or not isinstance(self.root_seed, int)
            or not 0 <= self.root_seed < 1 << 256
        ):
            # Fail the keyed rng post init path with ValueError for root seed must be an
            # unsigned 256-bit integer when isinstance and root seed is true; do not
            # continue ambiguously.
            raise ValueError("root_seed must be an unsigned 256-bit integer")

    def draw_bytes(
        self,
        *,
        component_id: ContentDigest,
        # Keep the causal id input explicit in the draw bytes contract.
        causal_id: ContentDigest,
        draw_index: int,
    ) -> bytes:
        # Execute the keyed rng draw bytes workflow in explicit, reviewable steps.
        if isinstance(draw_index, bool) or not isinstance(draw_index, int) or draw_index < 0:
            raise ValueError("draw_index must be a non-negative integer")
        key = self.root_seed.to_bytes(32, "big")
        message = (
            b"local-backtest/rng/v1\x00"
            # Keep the hex fromhex step visible while building message.
            + bytes.fromhex(component_id.hex)
            + bytes.fromhex(causal_id.hex)
            + draw_index.to_bytes(16, "big")
        )
        return hmac.new(key, message, sha256).digest()

    # Define keyed rng draw u64 as one focused operation with an explicit boundary.
    def draw_u64(
        self,
        *,
        component_id: ContentDigest,
        causal_id: ContentDigest,
        # Keep the draw index input explicit in the draw u64 contract.
        draw_index: int,
    ) -> int:
        # Execute the keyed rng draw u64 workflow in explicit, reviewable steps.
        return int.from_bytes(
            self.draw_bytes(
                component_id=component_id,
                causal_id=causal_id,
                draw_index=draw_index,
                # Complete draw_bytes only after its component id and causal id inputs are
                # visible in keyed rng draw u64.
            )[:8],
            "big",
        )


__all__ = ["RNG_ALGORITHM", "KeyedRng"]
