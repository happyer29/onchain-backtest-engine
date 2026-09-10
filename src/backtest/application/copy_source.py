"""Exact copy-source selection, shared by bounded inspection and preparation."""

from dataclasses import dataclass
from typing import cast

from backtest.domain.copytrading import require_solana_wallet
from backtest.domain.hashing import domain_digest

# Wallets and ranges carry immutable typed identities, not source endpoints.
from backtest.domain.identifiers import AccountId, ContentDigest, NetworkId, PositionSchemaId
from backtest.domain.time import BlockRange


@dataclass(frozen=True, slots=True)
class CopySourceSelection:
    """No source query may silently change wallets, decision cut or initialization history."""

    signing_wallets: tuple[AccountId, ...]
    decision_range: BlockRange
    history_range: BlockRange

    def __post_init__(self) -> None:
        """Creation history includes the decision interval and has an explicit lower bound."""
        if not isinstance(self.signing_wallets, tuple) or not 1 <= len(self.signing_wallets) <= 128:
            raise ValueError("copy source requires 1 to 128 signing wallets")
        for wallet in self.signing_wallets:
            require_solana_wallet(wallet)
        # Canonical membership is identity-bearing; duplicate or reordered input is rejected.
        ordered = tuple(sorted(set(self.signing_wallets), key=lambda wallet: wallet.value))
        if ordered != self.signing_wallets:
            raise ValueError("copy source signing wallets must be sorted and unique")
        decision, history = self.decision_range, self.history_range
        # Reject raw slot pairs that would lose the immutable network reference.
        if not isinstance(decision, BlockRange) or not isinstance(history, BlockRange):
            raise TypeError("copy source requires typed block ranges")
        # A lookback never expands the signal range or introduces another network.
        if (history.network_id, history.position_schema_id) != (
            decision.network_id,
            decision.position_schema_id,
        ):
            raise ValueError("copy source history and decision identities differ")
        # Creation lookback may extend only the left boundary, never the signal cut.
        if (
            history.from_block_ordinal > decision.from_block_ordinal
            or history.to_block_ordinal != decision.to_block_ordinal
        ):
            raise ValueError("copy history must begin no later and end with the decision range")

    def document(self) -> dict[str, object]:
        """Only immutable semantic selection enters the source configuration digest."""
        return {
            "signing_wallets": [wallet.value for wallet in self.signing_wallets],
            "decision_range": range_document(self.decision_range),
            "history_range": range_document(self.history_range),
        }

    # The configuration digest identifies selection, not publication time.

    @property
    def identity(self) -> ContentDigest:
        """Source selection is separate from the committed receipt or snapshot content ID."""
        return domain_digest("backtest.copy-source-selection.v1", self.document())


def range_document(value: BlockRange) -> dict[str, object]:
    """Ranges retain full chain identity and authoritative half-open coordinates."""
    return {
        "network_id": value.network_id.value,
        "position_schema_id": value.position_schema_id.value,
        "from_block_ordinal": value.from_block_ordinal,
        "to_block_ordinal": value.to_block_ordinal,
        # The upper coordinate is exclusive across inspection, planning and preparation.
    }


# Copy coverage is a separate evidence family from creation-only Sniping.
COPYBUY_COVERAGE_SCHEMA = "pumpfun-copybuy-coverage-evidence/v1"
COPYBUY_SOURCE_CONTRACT = "pumpfun-copybuy-source-contract/v1"
COPYBUY_UNIVERSE_POLICY_ID = "successful-sol-paired-non-mayhem-pumpfun-copy-buys-v1"


@dataclass(frozen=True, slots=True)
class CopyBuyCoverageEvidence:
    """Reconciled independent candidate enumeration and canonical eligible signal stream."""

    selection: CopySourceSelection
    candidate_occurrences: int
    eligible_occurrences: int
    excluded_occurrences: int
    candidate_mints: int
    # Both occurrence and mint totals reconcile; repeated leader buys remain observable.
    eligible_mints: int
    excluded_mints: int
    eligible_signal_digest: ContentDigest
    ordered_exclusion_digest: ContentDigest
    candidate_query_fingerprints: tuple[ContentDigest, ...]
    # The evidence schema is part of its canonical identity, never a parsing hint.
    schema: str = COPYBUY_COVERAGE_SCHEMA

    def __post_init__(self) -> None:
        """A partial enumeration or unmatched mint cannot masquerade as complete coverage."""
        if self.schema != COPYBUY_COVERAGE_SCHEMA or not isinstance(
            self.selection, CopySourceSelection
        ):
            raise ValueError("unsupported copy coverage contract")
        # Validate exact integer counts before checking either reconciliation equation.
        for name in (
            "candidate_occurrences",
            "eligible_occurrences",
            "excluded_occurrences",
            "candidate_mints",
            # Occurrence multiplicity and distinct mint coverage are independent measurements.
            "eligible_mints",
            "excluded_mints",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                # Negative, boolean or lossy counts cannot become source completeness evidence.
                raise ValueError("copy coverage counts must be nonnegative integers")
        # Known Mayhem is the only exclusion; missing creation is a failed proof.
        if self.candidate_occurrences != self.eligible_occurrences + self.excluded_occurrences:
            raise ValueError("copy occurrence coverage does not reconcile")
        if self.candidate_mints != self.eligible_mints + self.excluded_mints:
            raise ValueError("copy mint coverage does not reconcile")
        # Unique mint counts cannot exceed the source occurrences from which they derive.
        if (
            self.eligible_mints > self.eligible_occurrences
            or self.excluded_mints > self.excluded_occurrences
        ):
            raise ValueError("copy mint count exceeds its candidate occurrences")
        # Digests bind exact eligible signal order and explicitly classified exclusions.
        if not isinstance(self.eligible_signal_digest, ContentDigest) or not isinstance(
            self.ordered_exclusion_digest, ContentDigest
        ):
            raise TypeError("copy coverage requires exact content digests")
        fingerprints = self.candidate_query_fingerprints
        # Bound the query receipt closure even for a fragmented preparation range.
        # Query identities remain bounded, canonical and independent of credentials.
        if not isinstance(fingerprints, tuple) or not fingerprints or len(fingerprints) > 4096:
            raise ValueError("copy candidate queries require bounded exact fingerprints")
        if any(not isinstance(value, ContentDigest) for value in fingerprints):
            raise TypeError("copy candidate query fingerprint must be a content digest")
        if tuple(sorted(set(fingerprints), key=lambda value: value.hex)) != fingerprints:
            # Duplicate query identities cannot inflate the apparent inspected coverage.
            raise ValueError("copy candidate fingerprints must be sorted and unique")

    def identity_document(self) -> dict[str, object]:
        """The same bounded operands enter inspection, dataset and snapshot validation."""
        return {
            "schema": self.schema,
            "selection": self.selection.document(),
            "candidate_occurrences": self.candidate_occurrences,
            "eligible_occurrences": self.eligible_occurrences,
            # Eligible and excluded occurrences must reconcile with independent enumeration.
            "excluded_occurrences": self.excluded_occurrences,
            # Count both repeated source purchases and the immutable mint universe.
            "candidate_mints": self.candidate_mints,
            "eligible_mints": self.eligible_mints,
            "excluded_mints": self.excluded_mints,
            "eligible_signal_digest": self.eligible_signal_digest.hex,
            "ordered_exclusion_digest": self.ordered_exclusion_digest.hex,
            # Source query fingerprints prove which bounded operands produced the counts.
            "candidate_query_fingerprints": [
                value.hex for value in self.candidate_query_fingerprints
            ],
        }


# The codec retains the exact source-family schema and rejects transport extras.


def copy_coverage_from_document(value: object) -> CopyBuyCoverageEvidence:
    """Decode the closed coverage document used by both inspection and DatasetSpec."""
    data = _object(value)
    selection = copy_selection_from_document(data.get("selection"))
    queries = data.get("candidate_query_fingerprints")
    if not isinstance(queries, list):
        raise ValueError("candidate fingerprints must be an array")
    # Type checks precede construction; bool counts and lossy coercion are forbidden.
    result = CopyBuyCoverageEvidence(
        selection=selection,
        candidate_occurrences=_number(data.get("candidate_occurrences")),
        eligible_occurrences=_number(data.get("eligible_occurrences")),
        excluded_occurrences=_number(data.get("excluded_occurrences")),
        # Mint totals independently reconcile the selected token universe.
        candidate_mints=_number(data.get("candidate_mints")),
        eligible_mints=_number(data.get("eligible_mints")),
        excluded_mints=_number(data.get("excluded_mints")),
        eligible_signal_digest=ContentDigest(_text(data.get("eligible_signal_digest"))),
        ordered_exclusion_digest=ContentDigest(_text(data.get("ordered_exclusion_digest"))),
        # The model validates ordering, uniqueness and the bounded query count.
        candidate_query_fingerprints=tuple(ContentDigest(_text(item)) for item in queries),
        schema=_text(data.get("schema")),
    )
    # Exact re-encoding rejects fields that typed reconstruction would otherwise ignore.
    if result.identity_document() != data:
        raise ValueError("copy coverage has unknown or noncanonical fields")
    return result


def copy_selection_from_document(value: object) -> CopySourceSelection:
    """Exact wallet spelling and range identities survive every transport boundary."""
    data = _object(value)
    wallets = data.get("signing_wallets")
    if not isinstance(wallets, list):
        raise ValueError("copy signing wallets must be an array")
    # Construction validates canonical base58 and sorted, unique membership.
    result = CopySourceSelection(
        tuple(AccountId(_text(item)) for item in wallets),
        _range_from_document(data.get("decision_range")),
        _range_from_document(data.get("history_range")),
    )
    # Canonical wallet order survives inspection and later dataset reconstruction.
    if result.document() != data:
        raise ValueError("copy selection has unknown or noncanonical fields")
    return result


def _range_from_document(value: object) -> BlockRange:
    """Do not infer network identity from slot numbers or source endpoints."""
    data = _object(value)
    result = BlockRange(
        NetworkId(_text(data.get("network_id"))),
        PositionSchemaId(_text(data.get("position_schema_id"))),
        # Both half-open endpoints are authoritative integer coordinates.
        _number(data.get("from_block_ordinal")),
        _number(data.get("to_block_ordinal")),
    )
    # No endpoint, chain alias or default boundary is filled during range decoding.
    if range_document(result) != data:
        raise ValueError("copy range has unknown or noncanonical fields")
    return result


def _object(value: object) -> dict[str, object]:
    """Only JSON objects with string keys cross the coverage codec."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("copy evidence requires a JSON object")
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    """Never turn absent fields or numbers into apparently valid identifiers."""
    if not isinstance(value, str):
        raise ValueError("copy evidence text field is missing or invalid")
    return value


def _number(value: object) -> int:
    """Python bool is intentionally excluded from exact source counts and coordinates."""
    if type(value) is not int:
        raise ValueError("copy evidence integer field is missing or invalid")
    return value
