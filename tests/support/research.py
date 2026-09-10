"""Small observed-wallet fixtures with real-length, deterministic Solana values."""

import json
from pathlib import Path

# Explicit mode fixtures exercise the production classification seam without live claims.
from backtest.application.research import (
    SOL_QUOTE,
    ResearchDatasetSpec,
    ResearchTokenMode,
    TokenMode,
    # Swap multiplicity and participant roles remain separate from creation metadata.
    WalletObservation,
)

# Fixtures use the same explicit network and coordinate schema as production contracts.
from backtest.domain.chain import BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID
from backtest.domain.identifiers import ContentDigest, NetworkId, SourceId
from backtest.domain.time import BlockRange

# Every byte string is synthetic; these fixtures do not claim live source evidence.
DIGEST = ContentDigest("a" * 64)
NETWORK = NetworkId("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d")


def key(value: int, size: int = 32) -> str:
    """Encode a fixed nonzero byte pattern at the required public-key/signature size."""

    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(bytes([value]) * size, "big")
    result = ""
    while number:
        number, remainder = divmod(number, 58)
        # Leading zero bytes are absent because callers use positive fixture numbers.
        result = alphabet[remainder] + result
    return result


def dataset() -> ResearchDatasetSpec:
    """Keep the exact block interval shared across the source and local-store tests."""

    interval = BlockRange(NETWORK, BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID, 100, 200)
    return ResearchDatasetSpec(SourceId("research-test"), interval, DIGEST, DIGEST, DIGEST)


def observation(
    wallet: int, mint: int, block: int, seconds: int, *, side: str = "BUY", instruction: int = 0
) -> WalletObservation:
    """Separate the signing wallet from a common payer to expose role conflation."""

    return WalletObservation(
        block,
        1,
        instruction,
        key(block, 64),
        # Reported time and mint identify the market observation, not wallet ownership.
        seconds,
        key(mint),
        # Amounts exceed JavaScript's exact integer range and must stay exact end to end.
        SOL_QUOTE,
        side,
        100,
        10**18 + wallet,
        # A common fee payer deliberately differs from every participating signer.
        key(wallet),
        key(9),
    )


def observations() -> tuple[WalletObservation, ...]:
    """Two shared mints, a duplicate, a later rebuy and one unrelated seller."""

    first = observation(1, 5, 101, 1000)
    return (
        first,
        first,
        # The second signer is exactly on the inclusive window boundary; rebuy adds no vote.
        observation(2, 5, 102, 1060),
        observation(1, 5, 104, 1100),
        # Same transaction with different source instructions is a directional tie.
        observation(1, 6, 105, 1120),
        observation(2, 6, 105, 1120, instruction=2),
        observation(3, 7, 110, 1200, side="SELL"),
    )


def configuration(path: Path, data_root: Path) -> Path:
    """Use a small admitted single-host budget for hermetic research process tests."""

    path.write_text(
        "[paths]\n"
        + f"data_root = {json.dumps(str(data_root))}\n"
        + "[resources]\nmax_aggregate_child_memory_mb = 1024\nmax_builder_memory_mb = 256\n"
        "builder_peak_private_memory_mb = 512\nrun_peak_private_memory_mb = 512\n"
        # Keep disk and RAM safety reserves explicit even for the tiny test dataset.
        "tmp_quota_gb = 1\nmax_run_tmp_gb = 1\nmax_run_output_gb = 1\n"
        "disk_low_watermark_gb = 1\ndisk_emergency_watermark_gb = 1\n"
        "memory_safety_reserve_mb = 64\npage_cache_floor_mb = 64\n"
        "host_staging_output_reserve_mb = 64\nfixed_shared_overhead_mb = 64\n"
        # Frequent bounded progress lets isolated-process tests finish without long polling.
        "[control]\nprogress_interval_ms = 100\n",
        encoding="utf-8",
    )
    return path


def ordinary_modes(mints: tuple[str, ...]) -> tuple[ResearchTokenMode, ...]:
    """Explicit hermetic metadata places ordinary launches before every fixture observation."""

    return tuple(
        ResearchTokenMode(mint, TokenMode.NON_MAYHEM, (90, 1, 0, key(90, 64)), 1) for mint in mints
    )
