"""Dense all-signer calculations retain complete observations and hard resource guards."""

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
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
from tests.support.research import DIGEST, dataset, key, observation, observations


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


def test_wide_window_dense_result_fits_bounded_workspace(tmp_path: Path) -> None:
    """Every pair qualifies; compact work must finish without dropping any dense relationship."""
    store = LocalResearchStore(
        LocalArtifactRepository(tmp_path), memory_mb=64, temporary_bytes=192 * 1024**2
    )
    # Six hundred buyers of two mints produce 359400 evidence rows, all within 1000s.
    rows = tuple(
        replace(row, block_time_s=1000 + row.transaction_index) for row in _dense_rows(600, 2)
    )
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((rows,)))
    # Expected counts follow n*(n-1)/2 independently of the SQL execution strategy.
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, window_seconds=1000)
    result = store.analyze(spec)
    assert store.summary(result.artifact_id)["counts"] == {
        "source_rows": 1200,
        # Selection remains complete even though the dense intermediate relation is much larger.
        "selected_rows": 1200,
        "wallets": 600,
        "pairs": 179700,
        "evidence": 359400,
    }
    # Both endpoint pairs retain full lexical addresses, not internal dictionary keys.
    signers = sorted(_signer(index) for index in range(600))
    first = store.page(result.artifact_id, ResearchTable.PAIRS, after=-1, limit=1)[0]
    last = store.page(result.artifact_id, ResearchTable.PAIRS, after=179698, limit=1)[0]
    assert (first["signer_a"], first["signer_b"]) == (signers[0], signers[1])
    assert (last["signer_a"], last["signer_b"]) == (signers[-2], signers[-1])


# Physical parallelism must not change canonical row groups or the resulting Parquet bytes.
@pytest.mark.parametrize("threads", [1, 2])
def test_compact_work_preserves_original_table_bytes(tmp_path: Path, threads: int) -> None:
    """Frozen original bytes cover duplicates, transaction ties and sell-only activity."""
    expected = {
        "activity": "d57cfec63aa6caf708745da8d445c8b5d411d70c53ca609cd083619437df956e",
        "pairs": "73c76fd8ec5dd0a97d6388e2c246f3ee78c8e8a70e70232cf97eda77d4edde7b",
        "evidence": "bedb1e9396ae8359cf694f2e424843652a420348ff896183508b67a971429b62",
    }
    # These hashes were recorded from the prior string-based recipe, not the compact query.
    store = LocalResearchStore(LocalArtifactRepository(tmp_path), threads=threads)
    snapshot = store.publish_snapshot(dataset(), DIGEST, iter((observations(),)))
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, window_seconds=1000)
    result = store.analyze(spec)
    # Verify physical Parquet bytes as well as the independently asserted semantic fixture.
    with store.artifacts.open_committed(result.artifact_id) as handle:
        for role, digest in expected.items():
            with handle.open_binary(role + ".parquet") as stream:
                assert sha256(stream.read()).hexdigest() == digest


def test_compact_work_still_rejects_exhausted_spill(tmp_path: Path) -> None:
    """Compact representation must not bypass a smaller hard workspace quota."""
    repository = LocalArtifactRepository(tmp_path)
    source = LocalResearchStore(repository)
    rows = tuple(replace(row, block_time_s=1000) for row in _dense_rows(1200, 2))
    snapshot = source.publish_snapshot(dataset(), DIGEST, iter((rows,)))
    # The candidate guards admit this input, but native spill remains a separate hard bound.
    limited = LocalResearchStore(repository, memory_mb=64, temporary_bytes=1024)
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, window_seconds=1000)
    with pytest.raises(ResearchError, match="RESEARCH_MEMORY_LIMIT"):
        limited.analyze(spec)
    # Failure cannot leave a partial committed result or change the retained input.
    assert not tuple((tmp_path / "research-results").glob("**/COMMITTED"))
    assert source.summary(snapshot.artifact_id)["counts"]["source_rows"] == 2400
