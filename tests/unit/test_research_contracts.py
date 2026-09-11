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
    MODE_COLUMNS,
    MODE_SQL,
    SOURCE_COLUMNS,
    # Test raw scan and separate metadata lookup through the real source adapter.
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
        # Creation types are independently inspected; no source join can change swap multiplicity.
        self.mode_metadata = _Result(
            [
                (name, "String" if name in {"mint", "signature"} else "UInt64")
                # Each fixed creation column has a separately inspected physical type.
                for name in MODE_COLUMNS
            ]
        )
        self.mode_rows: list[tuple[object, ...]] = []
        # Separate call history and stream cleanup let failures assert resource handling.
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.rows = [item.values() for item in observations()]

    def query(self, query: str, **kwargs: Any) -> _Result:
        """Return inspection metadata without fabricating scan observations."""
        self.calls.append({"query": query, **kwargs})
        # The fake separates physical table schemas just as system.columns does.
        return (
            self.mode_metadata
            if kwargs["parameters"]["table"] == "pumpfun_token_creation"
            else self.metadata
        )

    # Stream cleanup is observable even when a yielded row violates the source contract.
    @contextmanager
    def query_row_block_stream(self, query: str, **kwargs: Any) -> Any:
        """Mirror the SDK context manager so rejects must close an opened stream."""
        self.calls.append({"query": query, **kwargs})
        try:
            yield iter((self.mode_rows if query == MODE_SQL else self.rows,))
        # Both successful consumption and validation exceptions must release the source.
        finally:
            self.closed = True


def test_source_is_explicit_bounded_multiplicity_preserving_and_closes() -> None:
    """Assert the remote query and limits directly, not through the implementation helper."""

    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    # Schema acceptance retains the explicit physical mapping in inspection identity.
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
    # Schema acceptance retains the explicit physical mapping in inspection identity.
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
    # Cleanup errors cannot disclose credentials through the public worker failure path.
    result = _prepare(settings, service, service.resolve_prepare(100, 200).canonical_bytes())
    assert service.summary(result.artifact_id)["counts"]["source_rows"] == 7
    assert client.closed and client.metadata.closed


def test_creation_lookup_is_bounded_exact_and_multiplicity_preserving() -> None:
    """Earlier creation and missing metadata remain distinct, without a join or latest rule."""

    client = _Client()
    row = (key(5), 90, 1, 0, key(90, 64), 0)
    client.mode_rows = [row, row, (key(6), 95, 1, 2, key(95, 64), True)]
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    # Exact repeats count as two source records; missing mint 7 retains no creation reference.
    modes = source.modes(spec, (key(5), key(6), key(7)))
    assert [mode.mode.value for mode in modes] == ["NON_MAYHEM", "MAYHEM", "UNKNOWN"]
    assert [mode.source_rows for mode in modes] == [2, 1, 0]
    assert modes[0].creation == (90, 1, 0, key(90, 64)) and modes[2].creation is None
    call = client.calls[-1]
    # The fixed authoritative creation range includes launches preceding the observation period.
    assert call["parameters"] == {
        "creation_start": 0,
        "creation_stop": 200,
        "mints": [key(5), key(6), key(7)],
    }
    # Scan and returned-result byte bounds independently constrain metadata acquisition.
    assert call["settings"]["max_rows_to_read"] == 20_000_000
    assert call["settings"]["max_bytes_to_read"] == 2 * 1024**3
    assert call["settings"]["max_result_rows"] == 2_000_000
    assert call["settings"]["max_result_bytes"] == 1024**3
    # Both scan and result overflow reject; no sampling or version winner is permitted.
    assert (
        call["settings"]["read_overflow_mode"]
        == call["settings"]["result_overflow_mode"]
        == "throw"
    )
    # Thread/time ceilings prevent an exact mint operand from authorizing unlimited work.
    assert call["settings"]["max_execution_time"] == 120 and call["settings"]["max_threads"] == 1
    assert all(
        word not in call["query"].upper()
        for word in ("FINAL", "OFFSET", "DISTINCT", "JOIN", "SELECT *")
    )
    # A successful complete metadata stream releases its driver resources.
    assert client.closed
    # Reordering exact source records cannot change classification or provenance counts.
    client.mode_rows.reverse()
    assert source.modes(spec, (key(5), key(6), key(7))) == modes


# Row validation rejects every malformed source category, not just a missing flag.
@pytest.mark.parametrize(
    "field,value",
    [(5, None), (5, 2), (5, "0"), (5, 0.0), (1, 200), (0, key(8)), (2, -1), (4, key(1))],
)
def test_invalid_creation_row_closes_lookup(field: int, value: object) -> None:
    """Null modes and out-of-scope or malformed identities never become ordinary tokens."""

    client = _Client()
    row: list[object] = [key(5), 90, 1, 0, key(90, 64), 0]
    row[field] = value
    client.mode_rows = [tuple(row)]
    source = ClickHouseResearchSource(client, database="source")
    # A typed source rejection closes the stream and returns no partial classification.
    with pytest.raises(ResearchError):
        source.modes(replace(dataset(), profile_digest=profile_digest()), (key(5),))
    assert client.closed


# Identity disagreement is fatal even when the mode itself stays unchanged.
@pytest.mark.parametrize(
    "field,value", [(5, 1), (1, 91), (2, 2), (3, 1), (4, key(91, 64)), (4, "")]
)
def test_creation_conflict_has_no_latest_first_or_majority_fallback(
    field: int, value: object
) -> None:
    """Every relevant creation identity component and mode must agree across source versions."""

    client = _Client()
    first: list[object] = [key(5), 90, 1, 0, key(90, 64), 0]
    conflicting = first.copy()
    conflicting[field] = value
    client.mode_rows = [tuple(first), tuple(first), tuple(conflicting)]
    # A majority of one version cannot legitimize a conflicting source record.
    source = ClickHouseResearchSource(client, database="source")
    with pytest.raises(ResearchError, match="MODE_CONFLICT"):
        source.modes(replace(dataset(), profile_digest=profile_digest()), (key(5),))
    assert client.closed


def test_creation_schema_is_required_and_nullable_modes_fail_inspection() -> None:
    """A valid swap schema cannot hide an unsupported nullable classification source."""

    client = _Client()
    client.mode_metadata.result_rows = [
        (name, "Nullable(UInt8)" if name == "mayhem_mode" else kind)
        for name, kind in client.mode_metadata.result_rows
    ]
    # A valid swap schema cannot compensate for unproven creation types.
    source = ClickHouseResearchSource(client, database="source")
    with pytest.raises(ResearchError, match="SCHEMA_MISMATCH"):
        source.inspect(replace(dataset(), profile_digest=profile_digest()))
    # Both metadata handles close before any data query is allowed.
    assert client.metadata.closed and client.mode_metadata.closed and len(client.calls) == 2


def test_creation_limits_and_legacy_command_reject_before_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty inputs skip IO; invalid operands and oversized source batches reject."""

    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    assert source.modes(spec, ()) == () and not client.calls
    for mints in ((key(5), key(5)), (key(6), key(5)), (key(5),) * 50_001):
        # Operand rejection precedes source contact and cannot be bypassed by duplicates.
        with pytest.raises(ResearchError, match="MINT_LIMIT"):
            source.modes(spec, mints)
    with pytest.raises(ResearchError, match="PROFILE_MISMATCH"):
        source.modes(replace(spec, schema_version=1), (key(5),))
    assert not client.calls
    # A small injected local cap exercises cumulative protection independently of remote settings.
    monkeypatch.setattr("backtest.adapters.source.clickhouse.research.MAX_SOURCE_ROWS", 1)
    client.mode_rows = [(key(5), 90, 1, 0, key(90, 64), 0)] * 2
    with pytest.raises(ResearchError, match="ROW_LIMIT"):
        source.modes(spec, (key(5),))
    assert client.closed


def test_versioned_mode_specs_and_provenance_are_closed() -> None:
    """Legacy identity survives; unknown schemas and fabricated provenance reject."""

    from backtest.application.research import (
        ResearchMode,
        ResearchTokenMode,
        TokenMode,
        # Stored provenance is independently validated after container authentication.
        token_mode_row,
    )

    # Reconstruct the original closed envelope instead of adding v2 defaults to its bytes.
    old = replace(dataset(), schema_version=1)
    assert dataset_spec(old.document()) == old
    legacy = WalletAnalysisSpec(ArtifactId("b" * 64), DIGEST, DIGEST, schema_version=1)
    # V1 omits the mode field entirely; v2 materializes it as a semantic operand.
    assert analysis_spec(legacy.document()) == legacy and "mode" not in legacy.document()
    with pytest.raises(ResearchError, match="INVALID_MODE"):
        replace(legacy, mode=ResearchMode.NON_MAYHEM)
    # Unknown generations must reject before any dictionary lookup or source operation.
    for schema in ("unknown", None, []):
        with pytest.raises(ResearchError):
            dataset_spec({**old.document(), "schema": schema})
    # Neither a future recipe nor arbitrary extra fields may execute under a current parser.
    with pytest.raises(ResearchError):
        analysis_spec({**legacy.document(), "schema": "future"})
    current = replace(legacy, schema_version=2)
    with pytest.raises(ResearchError, match="INVALID_MODE"):
        analysis_spec({**current.document(), "mode": "ordinary"})
    # Missing creation is an explicit UNKNOWN with zero source records, never a false mode.
    with pytest.raises(ResearchError, match="PROVENANCE"):
        ResearchTokenMode(key(5), TokenMode.NON_MAYHEM, None, 0)
    with pytest.raises(ResearchError, match="PROVENANCE"):
        ResearchTokenMode(key(5), TokenMode.UNKNOWN, (90, 1, 0, key(90, 64)), 1)
    # Shape, length and canonical encoding are mandatory even for an UNKNOWN classification.
    for reference in ("[]", "null", "x" * 513):
        with pytest.raises(ResearchError, match="PROVENANCE"):
            token_mode_row(key(5), "UNKNOWN", reference, 0)
    # Stored classifications have the same closed mode vocabulary as source-derived values.
    with pytest.raises(ResearchError, match="INVALID_MODE"):
        token_mode_row(key(5), "other", "", 0)


def test_creation_mint_fixed_string_48_is_an_explicit_physical_mapping() -> None:
    """Live creation mints use NUL-padded 48-byte storage without changing full address values."""

    client = _Client()
    source = ClickHouseResearchSource(client, database="source")
    spec = replace(dataset(), profile_digest=profile_digest())
    previous = source.inspect(spec)
    # Admit this measured physical mint representation while preserving its schema provenance.
    client.mode_metadata.result_rows = [
        (name, "FixedString(48)" if name == "mint" else kind)
        for name, kind in client.mode_metadata.result_rows
    ]
    # Schema acceptance retains the explicit physical mapping in inspection identity.
    assert source.inspect(spec) != previous
    assert "toStringCutToZero(mint)" in MODE_SQL
    # A storage width alone cannot legitimize malformed/truncated address values after projection.
    client.mode_rows = [("1" * 31, 90, 1, 0, key(90, 64), 0)]
    with pytest.raises(ResearchError, match="SOLANA_VALUE"):
        source.modes(spec, (key(5),))
    assert client.closed


@pytest.mark.parametrize("flag", [0, 1])
def test_empty_creation_signature_has_explicit_issue_and_retains_mode(flag: int) -> None:
    """Repeated partial source records preserve mode, coordinates and multiplicity."""

    from backtest.application.research import token_mode_row

    client = _Client()
    client.mode_rows = [(key(5), 90, 1, 0, "", flag)] * 2
    source = ClickHouseResearchSource(client, database="source")
    # Empty signature is the only exception; its issue is mandatory in committed provenance.
    row = source.modes(replace(dataset(), profile_digest=profile_digest()), (key(5),))[0]
    assert row.issue == "MISSING_CREATION_SIGNATURE" and row.source_rows == 2
    assert row.creation == (90, 1, 0, "")
    assert row.mode.value == ("MAYHEM" if flag else "NON_MAYHEM")
    # Stored partial references round-trip through the same strict immutable contract.
    assert token_mode_row(*row.values()) == row
    assert client.closed


@pytest.mark.parametrize("flag", [None, 2, "0", 0.0])
def test_empty_signature_does_not_excuse_invalid_mode(flag: object) -> None:
    """The approved data-completeness exception cannot silently classify a malformed flag."""

    client = _Client()
    client.mode_rows = [(key(5), 90, 1, 0, "", flag)]
    source = ClickHouseResearchSource(client, database="source")
    # Metadata failure closes the whole stream rather than publishing a partial warning list.
    with pytest.raises(ResearchError, match="INVALID_MODE"):
        source.modes(replace(dataset(), profile_digest=profile_digest()), (key(5),))
    assert client.closed


@pytest.mark.parametrize(
    "mode,reference,count,issue",
    [
        ("NON_MAYHEM", '[90,1,0,""]', 1, ""),
        ("NON_MAYHEM", '[90,1,0,""]', 1, "other"),
        # Unknown or absent creation cannot pretend to be a partially observed creation record.
        ("UNKNOWN", "", 0, "MISSING_CREATION_SIGNATURE"),
        ("NON_MAYHEM", "", 1, "MISSING_CREATION_SIGNATURE"),
        ("NON_MAYHEM", '[90,1,0,""]', 0, "MISSING_CREATION_SIGNATURE"),
        # The issue field is typed text, not an extensible object from a stored document.
        ("NON_MAYHEM", '[90,1,0,""]', 1, None),
    ],
)
def test_partial_creation_requires_matching_strict_provenance(
    mode: str, reference: str, count: int, issue: object
) -> None:
    """Only the approved exact issue/reference combination can be reinterpreted from disk."""

    from backtest.application.research import token_mode_row

    with pytest.raises(ResearchError):
        token_mode_row(key(5), mode, reference, count, issue)


def test_issue_cannot_mark_a_complete_signature_as_missing() -> None:
    """A contradictory warning is rejected even if its mode and creation signature are valid."""

    from backtest.application.research import ResearchTokenMode, TokenMode

    with pytest.raises(ResearchError, match="PROVENANCE"):
        ResearchTokenMode(
            key(5),
            TokenMode.NON_MAYHEM,
            (90, 1, 0, key(90, 64)),
            1,
            # Warning provenance must describe source facts, not an arbitrary caller exclusion.
            "MISSING_CREATION_SIGNATURE",
        )
