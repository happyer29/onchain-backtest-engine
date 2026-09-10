"""Versioned observational wallet research, separate from executable datasets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from backtest.domain.chain import BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID

# Research uses core identities without acquiring replay authority.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from backtest.domain.identifiers import ArtifactId, ContentDigest, NetworkId, SourceId
from backtest.domain.time import BlockRange

DATASET_SCHEMA: Final = "research-dataset-spec/v1"
# Artifact schemas are independent of existing canonical execution formats.
SNAPSHOT_SCHEMA: Final = "wallet-research-snapshot/v1"
ANALYSIS_SCHEMA: Final = "wallet-co-buy-analysis/v1"
RESULT_SCHEMA: Final = "wallet-research-result/v1"

# The initial source profile describes observations, not economic ownership.
SOURCE_PROFILE: Final = "pumpfun-v2-observed-sol-participation/v1"
OBSERVATION_SCHEMA: Final = "wallet-observations/v1"
SOL_QUOTE: Final = "So11111111111111111111111111111111111111112"
MAX_PAGE_SIZE: Final = 200
MAX_BLOCK_SPAN: Final = 300_000

# Calibrated dense-market caps retain all signers; native memory/time/spill guards still apply.
MAX_SOURCE_ROWS: Final = 2_000_000
MAX_PAIR_CANDIDATES: Final = 4_000_000
MAX_SIGNERS_PER_MINT: Final = 2_048
MAX_SELECTED_WALLETS: Final = 128
MAX_WINDOW_SECONDS: Final = 3_600

# These are byte-validation alphabets, not identity or deduplication policies.
_BASE58: Final = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_UINT64: Final = (1 << 64) - 1
_UINT32: Final = (1 << 32) - 1


class ResearchError(ValueError):
    """Expose only a stable safe code across source, job and HTTP boundaries."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ResearchTable(StrEnum):
    """Closed result table roles; callers never provide a filename or SQL."""

    OBSERVATIONS = "observations"
    ACTIVITY = "activity"
    PAIRS = "pairs"
    EVIDENCE = "evidence"


def integer(value: object, *, minimum: int = 0, maximum: int = _UINT64) -> int:
    """Reject bool, float, negative and overflowing source/transport values."""

    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ResearchError("RESEARCH_INVALID_INTEGER")
    return value


def text(value: object) -> str:
    """Require bounded text without control characters or hidden whitespace."""

    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
        raise ResearchError("RESEARCH_INVALID_TEXT")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ResearchError("RESEARCH_INVALID_TEXT")
    # Valid text is retained exactly; normalization must not merge source observations.
    return value


def solana_base58(value: object, *, size: int = 32) -> str:
    """Validate full public keys/signatures without inferring their ownership."""

    encoded = text(value)
    if len(encoded) > (44 if size == 32 else 88):
        raise ResearchError("RESEARCH_INVALID_SOLANA_VALUE")
    number = 0
    # Byte length, including leading zero bytes, rejects truncated display values.
    for character in encoded:
        if character not in _BASE58:
            raise ResearchError("RESEARCH_INVALID_SOLANA_VALUE")
        number = number * 58 + _BASE58.index(character)
    # Leading base58 ones encode zero bytes and must contribute to the decoded length.
    zeroes = len(encoded) - len(encoded.lstrip("1"))
    if zeroes + (number.bit_length() + 7) // 8 != size:
        raise ResearchError("RESEARCH_INVALID_SOLANA_VALUE")
    return encoded


def exact_object(value: object, keys: set[str]) -> dict[str, object]:
    """Keep every persisted command closed against unknown executable fields."""

    if not isinstance(value, dict) or set(value) != keys:
        raise ResearchError("RESEARCH_INVALID_DOCUMENT")
    return {text(key): item for key, item in value.items()}


@dataclass(frozen=True, slots=True)
class ResearchDatasetSpec:
    """Resolved fixed-profile acquisition; source credentials are never operands."""

    source_id: SourceId
    block_range: BlockRange
    profile_digest: ContentDigest
    code_digest: ContentDigest
    runtime_digest: ContentDigest

    # Typed identity operands are checked even when a trusted caller skips transport parsing.
    def __post_init__(self) -> None:
        """A narrow single-network range is mandatory even for observation-only work."""

        if not isinstance(self.source_id, SourceId) or not isinstance(self.block_range, BlockRange):
            raise ResearchError("RESEARCH_INVALID_DATASET")
        if not self.block_range.network_id.value.startswith("solana:"):
            raise ResearchError("RESEARCH_UNSUPPORTED_NETWORK")
        # Observations use exactly the same versioned coordinate schema on write and read.
        if self.block_range.position_schema_id != BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID:
            raise ResearchError("RESEARCH_UNSUPPORTED_POSITION_SCHEMA")
        # Existing BlockRange validates exact immutable network and UInt32 coordinates.
        span = self.block_range.to_block_ordinal - self.block_range.from_block_ordinal
        integer(span, minimum=1, maximum=MAX_BLOCK_SPAN)
        for digest in (self.profile_digest, self.code_digest, self.runtime_digest):
            # Configuration aliases cannot stand in for installed content identities.
            if not isinstance(digest, ContentDigest):
                raise ResearchError("RESEARCH_INVALID_DATASET")

    def document(self) -> dict[str, object]:
        """Serialize the complete immutable request, excluding physical limits."""

        return {
            "schema": DATASET_SCHEMA,
            "source_id": self.source_id.value,
            "network_id": self.block_range.network_id.value,
            # Chain coordinates remain authoritative; UTC is a reported attribute.
            "position_schema_id": self.block_range.position_schema_id.value,
            "from_block_ordinal": self.block_range.from_block_ordinal,
            "to_block_ordinal": self.block_range.to_block_ordinal,
            "profile": SOURCE_PROFILE,
            "profile_digest": self.profile_digest.hex,
            # Exact installed code and native runtime are rechecked by the child.
            "code_digest": self.code_digest.hex,
            "runtime_digest": self.runtime_digest.hex,
        }

    def canonical_bytes(self) -> bytes:
        """Share the same canonical document between CLI, API and the child."""

        return canonical_json_bytes(self.document())


def dataset_spec(value: object) -> ResearchDatasetSpec:
    """Decode only the new research schema; never reinterpret DatasetSpec v5."""

    fields = {"schema", "source_id", "network_id", "position_schema_id", "profile"}
    fields.update({"from_block_ordinal", "to_block_ordinal", "profile_digest"})
    fields.update({"code_digest", "runtime_digest"})
    document = exact_object(value, fields)
    # Research cannot select a different SQL/profile through a persisted command.
    if document["schema"] != DATASET_SCHEMA or document["profile"] != SOURCE_PROFILE:
        raise ResearchError("RESEARCH_UNSUPPORTED_SCHEMA")
    network = NetworkId(text(document["network_id"]))
    # Reconstruct generic core coordinates; only the source adapter knows Solana slots.
    block_range = BlockRange(
        network,
        BLOCK32_TRANSACTION32_POSITION_SCHEMA_ID,
        # Boundaries are authoritative typed block ordinals, with an exclusive upper limit.
        integer(document["from_block_ordinal"]),
        integer(document["to_block_ordinal"]),
    )
    # Position schemas are exact rather than a compatibility hint.
    if document["position_schema_id"] != block_range.position_schema_id.value:
        raise ResearchError("RESEARCH_UNSUPPORTED_SCHEMA")
    # The closed envelope becomes an immutable resolved acquisition only after validation.
    return ResearchDatasetSpec(
        SourceId(text(document["source_id"])),
        block_range,
        ContentDigest(text(document["profile_digest"])),
        # Existing digest validation rejects aliases and malformed hashes.
        ContentDigest(text(document["code_digest"])),
        ContentDigest(text(document["runtime_digest"])),
    )


@dataclass(frozen=True, slots=True)
class WalletAnalysisSpec:
    """One reviewed recipe over one exact observation snapshot."""

    snapshot_id: ArtifactId
    code_digest: ContentDigest
    runtime_digest: ContentDigest
    window_seconds: int = 60
    minimum_shared_mints: int = 2
    # An empty immutable selection means all observed signing-wallet addresses.
    wallets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject lossy, ambiguous or unbounded recipe parameters before enqueue."""

        integer(self.window_seconds, maximum=MAX_WINDOW_SECONDS)
        integer(self.minimum_shared_mints, minimum=1, maximum=MAX_SOURCE_ROWS)
        if not isinstance(self.wallets, tuple) or len(self.wallets) > MAX_SELECTED_WALLETS:
            raise ResearchError("RESEARCH_INVALID_WALLET_SELECTION")
        # Sorting and uniqueness are semantic so equivalent forms resolve identically.
        if self.wallets != tuple(sorted(set(self.wallets))):
            raise ResearchError("RESEARCH_INVALID_WALLET_SELECTION")
        for wallet in self.wallets:
            solana_base58(wallet)
        # Persist only strongly typed exact artifact and implementation identities.
        if not isinstance(self.snapshot_id, ArtifactId):
            raise ResearchError("RESEARCH_INVALID_ANALYSIS")
        if any(
            not isinstance(item, ContentDigest) for item in (self.code_digest, self.runtime_digest)
        ):
            # Recipe execution requires installed code and runtime digests, not display names.
            raise ResearchError("RESEARCH_INVALID_ANALYSIS")

    def document(self) -> dict[str, object]:
        """Keep presentation settings and operational quotas out of recipe identity."""

        return {
            "schema": ANALYSIS_SCHEMA,
            "snapshot_id": self.snapshot_id.hex,
            "code_digest": self.code_digest.hex,
            "runtime_digest": self.runtime_digest.hex,
            # Time-window equality is inclusive and therefore part of semantic identity.
            "window_seconds": self.window_seconds,
            # The threshold is applied to complete counts, never a truncated sample.
            "minimum_shared_mints": self.minimum_shared_mints,
            "wallets": list(self.wallets),
        }

    def canonical_bytes(self) -> bytes:
        """Use one serialization for request integrity, idempotency and execution."""

        return canonical_json_bytes(self.document())

    @property
    def build_key(self) -> ContentDigest:
        """Separate deterministic recipe lookup from the eventual artifact content ID."""

        return domain_digest(ANALYSIS_SCHEMA, self.document())


def analysis_spec(value: object) -> WalletAnalysisSpec:
    """Decode a complete recipe without allowing SQL, paths or future defaults."""

    fields = {"schema", "snapshot_id", "code_digest", "runtime_digest"}
    fields.update({"window_seconds", "minimum_shared_mints", "wallets"})
    document = exact_object(value, fields)
    if document["schema"] != ANALYSIS_SCHEMA or not isinstance(document["wallets"], list):
        raise ResearchError("RESEARCH_UNSUPPORTED_SCHEMA")
    # The dataclass validates selection order, size and complete Solana addresses.
    wallets = tuple(text(item) for item in document["wallets"])
    return WalletAnalysisSpec(
        ArtifactId(text(document["snapshot_id"])),
        ContentDigest(text(document["code_digest"])),
        ContentDigest(text(document["runtime_digest"])),
        # Integer validation rejects bools, floats and values outside the hard contract.
        integer(document["window_seconds"]),
        integer(document["minimum_shared_mints"]),
        wallets,
    )


# Observations remain value objects with no storage client or inferred ownership.
@dataclass(frozen=True, slots=True)
class WalletObservation:
    """A source row, not a globally deduplicated event or economic owner claim."""

    block_ordinal: int
    transaction_index: int
    source_instruction_index: int
    signature: str
    block_time_s: int
    # Asset and direction roles are retained explicitly for every observation.
    mint: str
    quote_asset: str
    side: str
    base_amount_atomic: int
    quote_amount_atomic: int
    # A fee payer never silently substitutes for the reported signing wallet.
    signing_wallet: str
    fee_payer: str

    def __post_init__(self) -> None:
        """Fail closed on malformed required facts without inventing missing roles."""

        integer(self.block_ordinal, maximum=_UINT32)
        integer(self.transaction_index, maximum=_UINT32)
        integer(self.source_instruction_index, maximum=_UINT32)
        integer(self.block_time_s, minimum=1, maximum=(1 << 63) - 1)
        # A dust leg may be zero, but a both-zero observation is not a successful swap.
        integer(self.base_amount_atomic)
        integer(self.quote_amount_atomic)
        if self.base_amount_atomic == self.quote_amount_atomic == 0:
            raise ResearchError("RESEARCH_INVALID_AMOUNT")
        # This initial source profile is restricted to observed SOL-paired BUY/SELL rows.
        if self.side not in {"BUY", "SELL"} or self.quote_asset != SOL_QUOTE:
            raise ResearchError("RESEARCH_UNSUPPORTED_OBSERVATION")
        # Validate complete keys while retaining their distinct source-reported roles.
        for address in (self.mint, self.signing_wallet, self.fee_payer):
            solana_base58(address)
        solana_base58(self.signature, size=64)
        # A quote token cannot also be the base asset of a supported observation.
        if self.mint == self.quote_asset:
            raise ResearchError("RESEARCH_UNSUPPORTED_OBSERVATION")

    def values(self) -> tuple[int | str, ...]:
        """A fixed logical row order makes hashing independent of source batching."""

        return (
            self.block_ordinal,
            self.transaction_index,
            self.source_instruction_index,
            # Transaction identity and reported time disambiguate the remaining attributes.
            self.signature,
            self.block_time_s,
            self.mint,
            self.quote_asset,
            # Include both amount and participant roles in the observation digest.
            self.side,
            self.base_amount_atomic,
            self.quote_amount_atomic,
            # Both source roles are hashed independently, even when their values coincide.
            self.signing_wallet,
            self.fee_payer,
        )
