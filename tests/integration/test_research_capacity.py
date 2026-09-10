"""Dense all-signer calculations retain complete observations and hard resource guards."""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

# Exercise the real local publication and recipe, with no source connection or signer filter.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.research.store import LocalResearchStore
from backtest.application.research import (
    ResearchError,
    ResearchTable,
    # Commands and observation rows retain the application's closed, typed contracts.
    WalletAnalysisSpec,
    WalletObservation,
)
from tests.support.research import DIGEST, dataset, key, observation


def _signer(index: int) -> str:
    """Encode distinct complete 32-byte public keys for more than 256 synthetic signers."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = index + 256
    digits = []
    # The fixture's positive two-byte suffix keeps the other thirty decoded bytes zero.
    while number:
        number, digit = divmod(number, 58)
        digits.append(alphabet[digit])
    return "1" * 30 + "".join(reversed(digits))


def _dense_rows(participants: int, mints: int) -> Iterator[WalletObservation]:
    """Every signer buys every mint; only the first pair is within the 180-second window."""
    base = observation(1, 5, 101, 1000)
    for mint in range(mints):
        for signer in range(participants):
            # The first pair lies exactly on the inclusive boundary; others remain far apart.
            seconds = 1180 if signer == 1 else 1000 + signer * 1000
            yield replace(
                base,
                signing_wallet=_signer(signer),
                mint=key(5 + mint),
                # Independent transaction positions make direction and time separately testable.
                block_time_s=seconds,
                transaction_index=signer,
            )


def test_empty_signer_selection_includes_dense_tokens_and_every_wallet(tmp_path: Path) -> None:
    """1200 buyers of three mints exceed both old guards but have one provable shared pair."""
    store = LocalResearchStore(LocalArtifactRepository(tmp_path), memory_mb=256)
    rows = tuple(_dense_rows(1200, 3))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((rows,)))
    # The empty selection is the actual public default, with no top-wallet fallback.
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, window_seconds=180)
    assert spec.wallets == ()
    result = store.analyze(spec)
    assert store.summary(result.artifact_id)["counts"] == {
        # Whole-result counts prove popular tokens and inactive-in-window signers survive.
        "source_rows": 3600,
        "selected_rows": 3600,
        "wallets": 1200,
        # Only the independently constructed boundary pair qualifies across the three mints.
        "pairs": 1,
        "evidence": 3,
    }
    pair = store.page(result.artifact_id, ResearchTable.PAIRS, after=-1, limit=1)[0]
    assert {pair["signer_a"], pair["signer_b"]} == {_signer(0), _signer(1)}
    # Every original mint contributes once to the same pair, including at exactly 180s.
    assert pair["shared_mints"] == "3"
    evidence = store.page(result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=3, pair=0)
    assert {row["mint"] for row in evidence} == {key(5), key(6), key(7)}
    assert all(abs(int(row["delta_seconds"])) == 180 for row in evidence)


# Separate fixtures cross one guard at a time; neither may publish a partial success.
@pytest.mark.parametrize("participants,mints", [(2049, 1), (1700, 3)])
def test_capacity_overflow_aborts(tmp_path: Path, participants: int, mints: int) -> None:
    """Reject per-mint overflow independently of total-candidate overflow before publication."""
    store = LocalResearchStore(LocalArtifactRepository(tmp_path), memory_mb=256)
    rows = tuple(_dense_rows(participants, mints))
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((rows,)))
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, window_seconds=180)
    # Respectively 2049 buyers or 4,332,450 potential pairs exceed the calibrated envelope.
    with pytest.raises(ResearchError, match="PAIR_CANDIDATE_LIMIT"):
        store.analyze(spec)
    assert not tuple((tmp_path / "research-results").glob("**/COMMITTED"))
    assert store.summary(snapshot.artifact_id)["counts"]["source_rows"] == participants * mints
