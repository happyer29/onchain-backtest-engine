"""Fail-closed command, key, source-schema and bounded query contracts."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from traceback import format_exception

# Fake SDK responses stay untyped, just as the real third-party boundary is.
from typing import Any

import pytest

# Exercise secret redaction at the actual source-enabled composition boundary.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository

# Source contracts are checked against recorded calls, without a live database.
from backtest.adapters.source.clickhouse.research import (
    SOURCE_COLUMNS,
    ClickHouseResearchSource,
    profile_digest,
)

# Command identity and observation validation remain application-owned.
from backtest.application.job_commands import ResolvedJobCommandError, resolve_job_command
from backtest.application.models import JobType
from backtest.application.research import (
    ResearchError,
    ResearchTable,
    # Analysis parameters and source observations are validated before durable execution.
    WalletAnalysisSpec,
    # Parsers must reject unrecognized operands instead of normalizing them away.
    analysis_spec,
    dataset_spec,
    solana_base58,
)

# Cursor scope is independent of artifact storage and carries no authority.
from backtest.application.research_pages import cursor_after, page_cursor
from backtest.bootstrap.config import load_settings
from backtest.bootstrap.research import _prepare, build_research_use_cases
from backtest.domain.identifiers import ArtifactId, ContentDigest

# The independent fixture explicitly distinguishes signer from fee payer.
from tests.support.research import DIGEST, NETWORK, configuration, dataset, key, observations


@pytest.mark.parametrize("value", ["", "mainnet", "0" * 32, "1" * 31, "1" * 33, key(1) + " "])
def test_invalid_solana_keys_fail_closed(value: str) -> None:
    """Display aliases, invalid alphabets and truncated addresses cannot become participants."""

    with pytest.raises(ResearchError):
        solana_base58(value)


# Coordinate validity is enforced before any local artifact can be staged.
@pytest.mark.parametrize(
    "field,value",
    [
        ("block_ordinal", True),
        ("transaction_index", -1),
        # Missing timestamps cannot establish a reported-time co-buy window.
        ("block_time_s", 0),
        # Missing amounts, unknown side and missing roles never become synthetic observations.
        ("base_amount_atomic", 1.5),
        ("quote_amount_atomic", 2**64),
        ("side", "UNKNOWN"),
        ("signing_wallet", None),
        # Role and transaction identities require complete keys of the correct byte length.
        ("fee_payer", ""),
        ("signature", key(1)),
    ],
)
def test_invalid_observation_fields_are_rejected(field: str, value: object) -> None:
    """A malformed source value cannot be upgraded to a valid observation."""
    with pytest.raises(ResearchError):
        replace(observations()[0], **{field: value})


def test_commands_and_cursors_are_closed_scoped_and_canonical() -> None:
    """Unknown fields and view changes are explicit rejects, not permissive defaults."""

    acquisition = dataset()
    assert dataset_spec(acquisition.document()) == acquisition
    analysis = WalletAnalysisSpec(ArtifactId("b" * 64), DIGEST, DIGEST)
    assert analysis_spec(analysis.document()) == analysis
    # Resolved queue closures contain one snapshot for analysis and none for acquisition.
    assert resolve_job_command(
        JobType.ANALYZE_WALLETS, analysis.canonical_bytes()
    ).input_artifact_ids == (analysis.snapshot_id,)
    # Acquisition has no existing local input; unknown command fields still fail closed.
    assert not resolve_job_command(
        JobType.PREPARE_RESEARCH, acquisition.canonical_bytes()
    ).input_artifact_ids
    # A query string cannot become an executable recipe through generic job submission.
    with pytest.raises(ResearchError):
        dataset_spec({**acquisition.document(), "sql": "SELECT * FROM arbitrary"})
    with pytest.raises(ResolvedJobCommandError):
        resolve_job_command(JobType.ANALYZE_WALLETS, b"{}")
    # Browser cursors are exclusive row locations bound to artifact, table and pair.
    cursor = page_cursor(analysis.snapshot_id, ResearchTable.EVIDENCE, 4, 9)
    assert cursor_after(cursor, analysis.snapshot_id, ResearchTable.EVIDENCE, 4) == 9
    # Every scope operand is binding, including the selected pair within an evidence table.
    for artifact, role, pair in (
        (ArtifactId("c" * 64), ResearchTable.EVIDENCE, 4),
        (analysis.snapshot_id, ResearchTable.PAIRS, 4),
        (analysis.snapshot_id, ResearchTable.EVIDENCE, 5),
        # These cases keep all other operands unchanged to isolate the rejected dimension.
    ):
        with pytest.raises(ResearchError, match="INVALID_CURSOR"):
            cursor_after(cursor, artifact, role, pair)
    # Non-canonical encodings must fail before any table reader is opened.
    with pytest.raises(ResearchError, match="INVALID_CURSOR"):
        cursor_after("?bad", analysis.snapshot_id, ResearchTable.EVIDENCE, 4)


class _Result:
    """Track metadata-reader cleanup independently from the streaming result."""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        """Expose the minimal SDK result surface used during schema inspection."""
        self.result_rows = rows
        self.closed = False

    def close(self) -> None:
        """Record that schema validation released its source result."""
        self.closed = True


class _Client:
    """Record actual source calls and exercise normal stream context cleanup."""

    def __init__(self) -> None:
        """Provide physical types separately from logical observation fixtures."""
        numeric = {"slot", "tx_idx", "ix_idx", "base_coin_amount", "quote_coin_amount", "failed"}
        self.metadata = _Result(
            [
                (
                    name,
                    # Integer amounts and positions stay exact; timestamps have second precision.
                    "UInt64"
                    if name in numeric
                    else "DateTime('UTC')"
                    if name == "block_time"
                    # String columns carry source roles, assets and the transaction signature.
                    else "String",
                )
                for name in SOURCE_COLUMNS
            ]
        )
        # Separate call history and stream cleanup let failures assert resource handling.
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.rows = [item.values() for item in observations()]

    def query(self, query: str, **kwargs: Any) -> _Result:
        """Return inspection metadata without fabricating scan observations."""
        self.calls.append({"query": query, **kwargs})
        return self.metadata

    @contextmanager
    def query_row_block_stream(self, query: str, **kwargs: Any) -> Any:
        """Mirror the SDK context manager so rejects must close an opened stream."""
        self.calls.append({"query": query, **kwargs})
        try:
            yield iter((self.rows,))
        # Both successful consumption and validation exceptions must release the source.
        finally:
            self.closed = True


def test_source_is_explicit_bounded_multiplicity_preserving_and_closes() -> None:
    """Assert the remote query and limits directly, not through the implementation helper."""

    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    assert source.inspect(spec)
    assert client.metadata.closed
    # Both duplicate observations survive the exact half-open source read.
    assert tuple(source.batches(spec)) == (observations(),)
    assert client.closed
    call = client.calls[-1]
    assert call["parameters"]["start"] == 100 and call["parameters"]["stop"] == 200
    assert call["settings"]["read_overflow_mode"] == "throw"
    # Source scans cannot deduplicate, join launch eligibility or query unbounded history.
    assert call["settings"]["max_rows_to_read"] == 20_000_000
    assert call["settings"]["max_result_rows"] == 2_000_000
    assert "slot >= {start:UInt64} AND slot < {stop:UInt64}" in call["query"]
    # The complete bounded result retains multiplicity instead of silently sampling rows.
    assert all(
        word not in call["query"].upper()
        for word in ("SELECT *", "OFFSET", "DISTINCT", "JOIN", "LIMIT")
    )
    assert str(call["transport_settings"]).find("source") == -1


# Nullable roles, finer unproven timestamps and floating amounts change source semantics.
@pytest.mark.parametrize(
    "column,type_name",
    [
        ("signing_wallet", "Nullable(String)"),
        ("block_time", "DateTime64(3)"),
        # A floating physical amount cannot be justified by the integer fixture values.
        ("base_coin_amount", "Float64"),
        # Dictionary encoding cannot hide nullability or redefine integer amount types.
        ("signing_wallet", "LowCardinality(Nullable(String))"),
        ("direction", "Nullable(LowCardinality(String))"),
        ("base_coin_amount", "LowCardinality(UInt64)"),
    ],
)
# Unsupported storage types must fail during inspection, before the first data scan.
def test_source_rejects_unproven_schema_before_scanning(column: str, type_name: str) -> None:
    """Inspection must reject unsupported physical types before opening the trade stream."""
    client = _Client()
    client.metadata.result_rows = [
        (name, type_name if name == column else kind) for name, kind in client.metadata.result_rows
    ]
    source = ClickHouseResearchSource(client, database="source")
    # The sole recorded call is schema inspection, and even that result is closed.
    with pytest.raises(ResearchError, match="SCHEMA_MISMATCH"):
        source.inspect(replace(dataset(), profile_digest=profile_digest()))
    assert len(client.calls) == 1 and client.metadata.closed


@pytest.mark.parametrize("column", ["quote_coin", "direction", "signing_wallet"])
def test_dictionary_encoded_strings_preserve_rows_and_physical_schema_identity(column: str) -> None:
    """Live source string dictionaries preserve values while retaining their observed type."""
    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    plain_schema = source.inspect(spec)
    # Dictionary storage is accepted only as the exact non-null String specialization.
    client.metadata.result_rows = [
        (name, "LowCardinality(String)" if name == column else kind)
        for name, kind in client.metadata.result_rows
    ]
    assert source.inspect(spec) != plain_schema
    assert client.metadata.closed
    # Decoding retains every value and duplicate; it adds no completeness claim.
    assert tuple(source.batches(spec)) == (observations(),)
    assert client.closed


def test_previous_source_profile_cannot_execute_under_new_schema_policy() -> None:
    """A queued v1 schema-policy request must be resolved again before any source read."""
    previous = ContentDigest("a607a90b95002460fa676b79e28ead390ae928418c61216a7756c9978de0e577")
    assert profile_digest() != previous
    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=previous)
    # Both metadata and row paths check the installed profile before opening remote work.
    with pytest.raises(ResearchError, match="SOURCE_PROFILE_MISMATCH"):
        source.inspect(spec)
    with pytest.raises(ResearchError, match="SOURCE_PROFILE_MISMATCH"):
        tuple(source.batches(spec))
    assert not client.calls


def test_source_range_failure_closes_stream_and_keeps_no_partial_success() -> None:
    """A row at the exclusive right bound invalidates the complete scan."""
    client = _Client()
    client.rows.append(replace(observations()[0], block_ordinal=200).values())
    source = ClickHouseResearchSource(client, database="source")
    # Driver cleanup remains mandatory when local validation catches a source violation.
    with pytest.raises(ResearchError, match="RANGE_MISMATCH"):
        tuple(source.batches(replace(dataset(), profile_digest=profile_digest())))
    assert client.closed


# A constructor failure and a failure after connection have different cleanup paths.
@pytest.mark.parametrize("phase", ["connect", "inspect", "scan"])
def test_source_sdk_failures_do_not_expose_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    """SDK error messages and exception context must never cross the redaction seam."""

    marker = "synthetic-secret-for-redaction-test"
    monkeypatch.setenv("BACKTEST_INDEXER_PASSWORD", marker)
    settings = load_settings(configuration(tmp_path / "profile.toml", tmp_path / "data"))
    store = LocalArtifactRepository(settings.paths.data_root)
    service = build_research_use_cases(settings, store, network_id=NETWORK)
    # Resolve the complete installed identity before simulating any source failure.
    payload = service.resolve_prepare(100, 200).canonical_bytes()
    client = _Client()
    closed = []

    def fail(*args: Any, **kwargs: Any) -> Any:
        """Model an SDK exception that embeds a credential in its message."""
        raise RuntimeError(marker)

    # Client cleanup remains observable when inspection or streaming raises.
    monkeypatch.setattr(client, "close", lambda: closed.append(True), raising=False)
    connect = fail if phase == "connect" else lambda **kwargs: client
    monkeypatch.setattr("backtest.bootstrap.research.clickhouse_connect.get_client", connect)
    if phase != "connect":
        # Both read APIs are called inside the same secret-redaction boundary.
        method = "query" if phase == "inspect" else "query_row_block_stream"
        monkeypatch.setattr(client, method, fail)
    with pytest.raises(ResearchError, match="RESEARCH_SOURCE_FAILED") as failure:
        _prepare(settings, service, payload)
    # Re-raising outside the catch must remove both the message and implicit exception context.
    assert marker not in "".join(format_exception(failure.value))
    assert failure.value.__context__ is None
    assert bool(closed) == (phase != "connect")
    assert not tuple((settings.paths.data_root / "research-snapshots").glob("**/COMMITTED"))


# Cleanup occurs after publication and has no authority to rewrite its successful result.
def test_source_publication_survives_secret_bearing_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An SDK close failure cannot invalidate already verified committed output."""

    monkeypatch.setenv("BACKTEST_INDEXER_PASSWORD", "synthetic-password")
    settings = load_settings(configuration(tmp_path / "profile.toml", tmp_path / "data"))
    store = LocalArtifactRepository(settings.paths.data_root)
    service = build_research_use_cases(settings, store, network_id=NETWORK)
    client = _Client()
    # Publication consumes the real fixed-profile reader and real local artifact adapter.
    monkeypatch.setattr(
        "backtest.bootstrap.research.clickhouse_connect.get_client", lambda **kwargs: client
    )

    def close() -> None:
        """Keep even secret-bearing cleanup errors within the source boundary."""
        raise RuntimeError("synthetic-password")

    monkeypatch.setattr(client, "close", close, raising=False)
    result = _prepare(settings, service, service.resolve_prepare(100, 200).canonical_bytes())
    assert service.summary(result.artifact_id)["counts"]["source_rows"] == 7
    assert client.closed and client.metadata.closed
