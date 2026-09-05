"""Strong, infrastructure-independent identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SHA256_RE = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_NETWORK_FAMILY_RE = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
# Bind position schema re once as an explicit module-level contract.
_POSITION_SCHEMA_RE = re.compile(r"[a-z][a-z0-9-]*-v[1-9][0-9]*\Z")
_MUTABLE_NETWORK_ALIASES = frozenset(
    {
        "devnet",
        "mainnet",
        # Pass mainnet-beta explicitly so frozenset receives a reviewable devnet and
        # mainnet input in module.
        "mainnet-beta",
        "production",
        "testnet",
    }
)

# Solana genesis hashes encode exactly 32 bytes; the alphabet excludes ambiguous glyphs.
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_DIGITS = {character: digit for digit, character in enumerate(_BASE58_ALPHABET)}
_SOLANA_GENESIS_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")


def _validate_solana_genesis_reference(value: str) -> None:
    """Reject abbreviated or malformed genesis hashes without rewriting identity bytes."""
    if _SOLANA_GENESIS_RE.fullmatch(value) is None:
        raise ValueError("Solana network reference must be a complete base58 genesis hash")

    # At most 44 digits are decoded, bounding work independently of caller input size.
    decoded = 0
    for character in value:
        decoded = decoded * 58 + _BASE58_DIGITS[character]

    # Each leading '1' represents a zero byte omitted from the integer's bit length.
    leading_zero_bytes = len(value) - len(value.lstrip("1"))
    significant_bytes = (decoded.bit_length() + 7) // 8
    if leading_zero_bytes + significant_bytes != 32:
        raise ValueError("Solana network reference must encode exactly 32 genesis bytes")


# Apply dataclass semantics to the following identifier contract.
@dataclass(frozen=True, slots=True, order=True)
class Identifier:
    """A validated opaque identifier.

    Identifiers deliberately do not know anything about paths, hosts or database
    primary keys.  This keeps logical identity outside infrastructure adapters.
    """

    value: str

    def __post_init__(self) -> None:
        # Execute the identifier post init workflow in explicit, reviewable steps.
        if not isinstance(self.value, str):
            raise TypeError("identifier value must be a string")
        if not self.value or self.value != self.value.strip():
            raise ValueError("identifier must be non-empty and have no outer whitespace")
        if len(self.value) > 256:
            # Fail the identifier post init path with ValueError for identifier is longer
            # than 256 characters when value is true; do not continue ambiguously.
            raise ValueError("identifier is longer than 256 characters")
        if any(ord(character) < 32 for character in self.value):
            raise ValueError("identifier must not contain control characters")

    def __str__(self) -> str:
        return self.value


# Apply dataclass semantics to the following content digest contract.
@dataclass(frozen=True, slots=True, order=True)
class ContentDigest(Identifier):
    """A SHA-256 digest, with an optional ``sha256:`` display prefix."""

    def __post_init__(self) -> None:
        # Execute the content digest post init workflow in explicit, reviewable steps.
        Identifier.__post_init__(self)
        if _SHA256_RE.fullmatch(self.value) is None:
            raise ValueError("content digest must be a lowercase SHA-256 digest")

    @property
    def hex(self) -> str:
        # Return the completed content digest hex result without a hidden fallback.
        return self.value.removeprefix("sha256:")


class SourceId(Identifier):
    """Logical source identifier; never a DSN or endpoint."""


class CapabilityId(Identifier):
    """Logical data capability, for example ``solana.blocks.v1``."""


@dataclass(frozen=True, slots=True, order=True)
class NetworkId(Identifier):
    """Exact chain identity as ``family:immutable-chain-reference``.

    Human aliases such as ``mainnet`` are intentionally not accepted.  A
    family may use a genesis hash, immutable chain UUID or another stable
    reference, but endpoint names and mutable environment labels are not chain
    identities.
    """

    def __post_init__(self) -> None:
        # Separate the generic family/reference envelope before interpreting its contents.
        Identifier.__post_init__(self)
        family, separator, chain_reference = self.value.partition(":")
        if not separator or not family or not chain_reference:
            raise ValueError("network ID must use family:immutable-chain-reference")

        # Canonical family spelling and mutable aliases must never produce semantic IDs.
        if _NETWORK_FAMILY_RE.fullmatch(family) is None:
            raise ValueError("network family must be lowercase kebab-case")
        if chain_reference.casefold() in _MUTABLE_NETWORK_ALIASES:
            raise ValueError("network ID must not use a mutable network alias")

        # URI paths, queries and credential delimiters belong only in operational config.
        if any(character.isspace() for character in chain_reference):
            raise ValueError("network chain reference must not contain whitespace")
        if any(delimiter in chain_reference for delimiter in ("/", "\\", "?", "#", "@")):
            raise ValueError("network chain reference must not contain endpoint or credentials")

        # Validate the existing Solana representation without admitting another network.
        if family == "solana":
            _validate_solana_genesis_reference(chain_reference)

    # Apply property semantics to the following network id family contract.
    @property
    def family(self) -> str:
        return self.value.partition(":")[0]

    @property
    def chain_reference(self) -> str:
        # Return the completed network id chain reference result without a hidden
        # fallback.
        return self.value.partition(":")[2]


@dataclass(frozen=True, slots=True, order=True)
class PositionSchemaId(Identifier):
    """Versioned interpretation of generic chain-position coordinates."""

    def __post_init__(self) -> None:
        # Execute the position schema id post init workflow in explicit, reviewable steps.
        Identifier.__post_init__(self)
        if _POSITION_SCHEMA_RE.fullmatch(self.value) is None:
            raise ValueError("position schema ID must be versioned lowercase kebab-case")


@dataclass(frozen=True, slots=True, order=True)
class ProtocolPayloadSchemaId(Identifier):
    """Versioned schema for protocol-owned canonical payload bytes."""

    def __post_init__(self) -> None:
        # Execute the protocol payload schema id post init workflow in explicit,
        # reviewable steps.
        Identifier.__post_init__(self)
        if _POSITION_SCHEMA_RE.fullmatch(self.value) is None:
            raise ValueError("protocol payload schema ID must be versioned lowercase kebab-case")


class ArtifactId(ContentDigest):
    """Content identifier of a committed artifact."""


class SnapshotId(ArtifactId):
    """Exact root snapshot artifact identifier."""


class ReplayPackId(ArtifactId):
    """Exact ReplayPack artifact identifier."""


class DeliveryScheduleId(ArtifactId):
    """Exact materialized delivery-schedule identifier."""


class DatasetRevisionId(ContentDigest):
    """Logical dataset content plus its exact source and projector boundary."""


class LogicalContentHash(ContentDigest):
    """Canonical record identity independent of compression and local paths."""


class BundleId(ContentDigest):
    """Immutable code/config bundle identity."""


class RuntimeLockId(ContentDigest):
    """Immutable physical runtime identity for one execution attempt."""


class FeatureSetId(ArtifactId):
    """Exact immutable point-in-time feature overlay."""


class LabelSetId(ArtifactId):
    """Exact immutable training-only label overlay."""


class UniverseId(ArtifactId):
    """Exact immutable point-in-time universe definition."""


class PredictionSetId(ArtifactId):
    """Exact immutable causal prediction overlay."""


class ModelBundleId(ArtifactId):
    """Exact immutable trained-model bundle."""


class ModelScheduleId(ArtifactId):
    """Exact immutable walk-forward model schedule."""


class LogicalRunId(ContentDigest):
    """Logical experiment identity, independent of physical execution."""


class ExecutionAttemptId(ContentDigest):
    """Physical identity of one run attempt and its exact runtime inputs."""


class AssetId(Identifier):
    """Canonical asset identifier; dictionary-encoded outside the domain."""


class PoolId(Identifier):
    """Canonical venue or liquidity-pool identifier."""


class VenueId(Identifier):
    """Canonical protocol venue identifier independent of venue implementation."""


class FeeComponentId(Identifier):
    """Stable semantic identity of one fee route or component."""


class AccountId(Identifier):
    """Canonical ledger account identifier."""


class OrderId(ContentDigest):
    """Deterministic order identity derived from causal coordinates."""


class JobId(Identifier):
    """Operational local job identifier."""


class AttemptId(Identifier):
    """Operational execution-attempt identifier."""
