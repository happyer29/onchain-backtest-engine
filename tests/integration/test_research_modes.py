"""Independent mode-filter arithmetic, legacy compatibility and atomic failure tests."""

from dataclasses import replace
from pathlib import Path

import pytest

# The tests exercise real atomic publication and bounded native analytical queries.
from backtest.adapters.artifacts.localfs import LocalArtifactRepository
from backtest.adapters.research.store import LocalResearchStore
from backtest.application.models import ArtifactDraft, CommittedArtifact

# Classification is a separate fact from the unchanged wallet observations.
from backtest.application.research import (
    LEGACY_RESULT_SCHEMA,
    LEGACY_SNAPSHOT_SCHEMA,
    ResearchError,
    # Recipe filtering and raw token classification are different closed domains.
    ResearchMode,
    ResearchTable,
    ResearchTokenMode,
    TokenMode,
    # Exact analysis identity remains independent of eventual committed content IDs.
    WalletAnalysisSpec,
)
from backtest.application.use_cases.research import ResearchUseCases

# Independent legacy manifests use the existing core publication and hashing contract.
from backtest.domain.hashing import canonical_json_bytes, domain_digest
from tests.support.research import DIGEST, NETWORK, dataset, key, observations, ordinary_modes


def mixed_modes(mints: tuple[str, ...]) -> tuple[ResearchTokenMode, ...]:
    """Mint 5 is ordinary, 6 is Mayhem, and the seller's mint 7 has no creation evidence."""

    result = []
    for mint in mints:
        mode = TokenMode.NON_MAYHEM if mint == key(5) else TokenMode.MAYHEM
        creation = (90, 1, 0, key(90, 64))
        # Missing evidence is explicit and cannot silently add an ordinary token.
        result.append(
            ResearchTokenMode(mint, mode, creation, 2)
            if mint != key(7)
            else ResearchTokenMode(mint, TokenMode.UNKNOWN, None, 0)
        )
    # The bounded classifier returns canonical input mint order, including explicit absences.
    return tuple(result)


# The arithmetic oracle has one token in each category and an exact duplicated swap.
def test_mode_filter_precedes_threshold_and_preserves_wallets(tmp_path: Path) -> None:
    """A two-token pair disappears at threshold two but survives on its ordinary mint at one."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=mixed_modes
    )
    # ALL establishes the original two-token relation for the same retained observations.
    base = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST)
    all_result = store.analyze(base)
    # The mixed snapshot keeps all seven original rows, including both exact repeats.
    summary = store.summary(snapshot.artifact_id)
    assert summary["counts"]["source_rows"] == 7
    # Reconciliation covers both row multiplicity and distinct mints in each category.
    assert summary["mode_counts"] == {
        "non_mayhem_rows": 4,
        "non_mayhem_mints": 1,
        # Mayhem counts cannot absorb missing classifications.
        "mayhem_rows": 2,
        "mayhem_mints": 1,
        "unknown_rows": 1,
        # Unknown mints are counted independently instead of being labeled ordinary.
        "unknown_mints": 1,
    }
    # Mode is a semantic operand, so different scopes cannot share a recipe/content identity.
    filtered = replace(base, mode=ResearchMode.NON_MAYHEM)
    assert filtered.build_key != base.build_key
    no_pair = store.analyze(filtered)
    assert store.summary(all_result.artifact_id)["counts"]["pairs"] == 1
    assert store.summary(no_pair.artifact_id)["counts"]["pairs"] == 0
    # The same wallets still appear in activity; Mayhem participation does not blacklist them.
    assert store.summary(no_pair.artifact_id)["counts"]["selected_rows"] == 4
    activity = store.page(no_pair.artifact_id, ResearchTable.ACTIVITY, after=-1, limit=25)
    assert {row["signing_wallet"] for row in activity} == {key(1), key(2)}
    pair_result = store.analyze(replace(filtered, minimum_shared_mints=1))
    # Complete counts and drilldown now refer only to ordinary mint 5.
    pairs = store.page(pair_result.artifact_id, ResearchTable.PAIRS, after=-1, limit=25)
    assert pairs[0]["shared_mints"] == "1"
    # Evidence must point only to the retained ordinary token after threshold recalculation.
    evidence = store.page(
        pair_result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=25, pair=0
    )
    assert [row["mint"] for row in evidence] == [key(5)]


# Source order and native scheduling may change physical work but never semantic output.
def test_mode_counts_use_signer_scope_before_filter_and_are_deterministic(tmp_path: Path) -> None:
    """Counters reconcile; batching and native threads do not change bytes."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=mixed_modes
    )
    # A fresh mutable-source scan over identical bytes must reconstruct the same snapshot.
    reverse = tuple(reversed(observations()))
    repeat = store.publish_snapshot(
        dataset(), DIGEST, iter((reverse[:2], reverse[2:])), classify=mixed_modes
    )
    assert repeat.artifact_id == snapshot.artifact_id
    # One signer has three ordinary rows and one Mayhem row; unrelated unknown mint is absent.
    spec = WalletAnalysisSpec(
        snapshot.artifact_id, DIGEST, DIGEST, wallets=(key(1),), mode=ResearchMode.NON_MAYHEM
    )
    # Only the chosen signer contributes to pre-mode counters and activity.
    result = store.analyze(spec)
    summary = store.summary(result.artifact_id)
    assert summary["counts"]["source_rows"] == 7 and summary["counts"]["selected_rows"] == 3
    # Reconciliation covers both row multiplicity and distinct mints in each category.
    assert summary["mode_counts"] == {
        "non_mayhem_rows": 3,
        "non_mayhem_mints": 1,
        # Mayhem counts cannot absorb missing classifications.
        "mayhem_rows": 1,
        "mayhem_mints": 1,
        "unknown_rows": 0,
        # Unknown mints are counted independently instead of being labeled ordinary.
        "unknown_mints": 0,
    }
    # Mode filtering retains deterministic canonical publication under native scheduling changes.
    assert (
        LocalResearchStore(store.artifacts, threads=2).analyze(spec).artifact_id
        == result.artifact_id
    )


# Reject incomplete classification before any authoritative artifact can be published.
@pytest.mark.parametrize("failure", ["missing", "extra", "order", "late", "source", "absent"])
def test_classification_failure_publishes_no_snapshot(tmp_path: Path, failure: str) -> None:
    """Incomplete/conflicting metadata cannot produce an apparently valid snapshot root."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    consumed = False

    def batches():
        """The classifier must receive the complete observation universe, not the first batch."""
        nonlocal consumed
        yield observations()
        consumed = True

    # Use an explicitly failing port rather than relying on incidental SQL or file errors.
    def classify(mints):
        """Return one isolated malformed classification shape or a source failure."""
        assert consumed and mints == tuple(sorted({row.mint for row in observations()}))
        modes = ordinary_modes(mints)
        if failure == "source":
            raise ResearchError("RESEARCH_SOURCE_FAILED")
        # Each violation must abort all tables, including already-spooled observations.
        if failure == "missing":
            return modes[:-1]
        if failure == "extra":
            return (*modes, modes[0])
        # One row per mint is insufficient if canonical mint ordering is violated.
        if failure == "order":
            return tuple(reversed(modes))
        # A creation after the first observed buy cannot classify that earlier observation.
        return (replace(modes[0], creation=(190, 1, 0, key(90, 64))), *modes[1:])

    # Both missing source capability and malformed classifications abort preparation.
    with pytest.raises(ResearchError):
        store.publish_snapshot(
            dataset(), DIGEST, batches(), classify=None if failure == "absent" else classify
        )
    assert not tuple(tmp_path.rglob("COMMITTED"))


# Compatibility fixtures construct closed v1 metadata without changing any source table bytes.
def _legacy_copy(
    store: LocalResearchStore,
    source: CommittedArtifact,
    *,
    # A provided snapshot switches this fixture from a v1 acquisition to a derived result.
    snapshot: CommittedArtifact | None = None,
) -> CommittedArtifact:
    """Build a genuinely closed v1 envelope from immutable tables, without migrating any bytes."""

    summary = store.summary(source.artifact_id)
    manifest = {
        key: value
        for key, value in summary.items()
        # Transport decoration and v2-only counters have no place in a closed v1 envelope.
        if key not in {"artifact_id", "kind", "mode_counts", "data_issue_counts"}
    }
    # The old dataset profile and version retain their original readable meaning.
    manifest["dataset"] = replace(dataset(), schema_version=1).document()
    if snapshot is None:
        # V1 snapshots contain observations only and use their original build-key domain.
        manifest["schema"] = LEGACY_SNAPSHOT_SCHEMA
        manifest["tables"] = {"observations": summary["tables"]["observations"]}
        build = domain_digest(LEGACY_SNAPSHOT_SCHEMA, manifest)
        inputs = ()
    else:
        # V1 recipe omits mode entirely and retains its original ALL identity.
        spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, schema_version=1)
        manifest.update(schema=LEGACY_RESULT_SCHEMA, analysis=spec.document())
        manifest["tables"] = {k: v for k, v in summary["tables"].items() if k != "data_issues"}
        # Only original result roles belong to the independently constructed v1 fixture.
        build, inputs = spec.build_key, (snapshot.artifact_id,)
    # Fixture publication obeys writer-before-reader lock order and exact dependency closure.
    writer = store.artifacts.stage(ArtifactDraft(source.kind, build, inputs))
    handle = store.artifacts.open_committed(source.artifact_id)
    try:
        # Publication uses the same verified handle and protocol as all artifact fixtures.
        for table in manifest["tables"]:
            with (
                handle.open_binary(table + ".parquet") as old,
                writer.open_binary(table + ".parquet") as new,
            ):
                # Tiny fixture tables are copied verbatim, with no reinterpretation of their rows.
                new.write(old.read())
        return writer.commit(canonical_json_bytes(manifest))
    # Cleanup and abort remain mandatory for failed compatibility-fixture publication.
    except BaseException:
        writer.abort()
        raise
    finally:
        handle.close()


# Legacy readers and new executable recipes have separate compatibility boundaries.
def test_legacy_read_all_analysis_and_non_mayhem_reprepare(tmp_path: Path) -> None:
    """Legacy bytes stay readable; NON_MAYHEM rejects before queue and worker."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    current = store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=ordinary_modes
    )
    # Use a committed v1 snapshot to test rejection rather than mocking its summary.
    legacy = _legacy_copy(store, current)
    service = ResearchUseCases(store, DIGEST, DIGEST, DIGEST, dataset().source_id, NETWORK)
    with pytest.raises(ResearchError, match="REPREPARE_REQUIRED"):
        service.resolve_analysis(legacy.artifact_id)
    # Explicit ALL supports the old observation set without inventing mode evidence.
    spec = service.resolve_analysis(legacy.artifact_id, mode=ResearchMode.ALL)
    result = store.analyze(spec)
    assert store.summary(result.artifact_id)["mode_counts"]["unknown_rows"] == 7
    old_result = _legacy_copy(store, result, snapshot=legacy)
    old_summary = store.summary(old_result.artifact_id)
    # Historical recipe bytes contain no new mode/default field and still explain exact evidence.
    assert "mode" not in old_summary["analysis"] and "mode_counts" not in old_summary
    assert store.page(old_result.artifact_id, ResearchTable.EVIDENCE, after=-1, limit=25, pair=0)
    with pytest.raises(ResearchError, match="REPREPARE_REQUIRED"):
        store.analyze(replace(spec, mode=ResearchMode.NON_MAYHEM))
    # A queued v1 recipe cannot execute under the current installed v2 implementation.
    with pytest.raises(ResearchError, match="RERESOLVE_REQUIRED"):
        store.analyze(replace(spec, schema_version=1))


def test_mode_table_corruption_cannot_reach_analysis(tmp_path: Path) -> None:
    """Changing classified bytes invalidates the retained input before calculation."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=mixed_modes
    )
    # Byte corruption must be caught by repository verification before native calculation.
    path = tmp_path / "research-snapshots" / snapshot.artifact_id.hex / "token_modes.parquet"
    content = path.read_bytes()
    path.write_bytes(content[:20] + b"broken" + content[26:])
    # Filesystem content authentication precedes Arrow parsing and cannot return partial results.
    with pytest.raises((RuntimeError, ValueError)):
        store.analyze(
            WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, mode=ResearchMode.NON_MAYHEM)
        )
    assert not tuple((tmp_path / "research-results").rglob("COMMITTED"))


# Transport tests retain session/CSRF and idempotency semantics while adding the mode field.
def test_api_mode_defaults_identity_legacy_and_invalid_forms(tmp_path: Path) -> None:
    """The same typed resolver controls API defaults, exact mode identity and legacy rejection."""

    from fastapi.testclient import TestClient

    from backtest.bootstrap.config import load_settings
    from backtest.bootstrap.container import build_runtime_container

    # HTTP tests use the real queue/security boundary without executing source work in a request.
    from backtest.domain.identifiers import JobId
    from backtest.interfaces.api import create_app
    from tests.support.research import configuration

    # Real composition provides the same resolver used by CLI and isolated workers.
    config = configuration(tmp_path / "profile.toml", tmp_path / "data")
    container = build_runtime_container(load_settings(config), profile="research-modes")
    service = container.control.research
    assert service is not None
    # Both snapshot generations are genuinely committed, not mocked API summaries.
    snapshot = service.store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=incomplete_modes
    )
    legacy = _legacy_copy(service.store, snapshot)
    # Commands require the ordinary same-origin session and explicit intent key.
    headers = {
        "X-Backtest-CSRF": "1",
        "Origin": "http://127.0.0.1",
        "Idempotency-Key": "mode-default",
    }
    # Opening the page establishes the session cookie required for a real mutation.
    client = TestClient(
        create_app(container.control, control_plane_id=DIGEST), base_url="http://127.0.0.1"
    )
    assert client.get("/research").status_code == 200
    form = {"snapshot_id": snapshot.artifact_id.hex}
    # Omitting mode resolves NON_MAYHEM once in application code, with canonical queue bytes.
    response = client.post("/api/v1/research/analyze", json=form, headers=headers)
    assert response.status_code == 202, response.text
    job = container.jobs.get_job(JobId(response.json()["job_id"]))
    # Compare complete bytes, including the resolved default, rather than just the mode label.
    assert (
        job.spec.canonical_payload
        == service.resolve_analysis(snapshot.artifact_id).canonical_bytes()
    )
    assert b'"mode":"NON_MAYHEM"' in job.spec.canonical_payload
    # Reusing an intent key with a changed mode cannot silently change the queued calculation.
    conflict = client.post(
        "/api/v1/research/analyze", json={**form, "mode": "ALL"}, headers=headers
    )
    assert conflict.status_code == 409
    # A deliberate new mode is a new intent with a separate key.
    headers["Idempotency-Key"] = "mode-all"
    response = client.post(
        "/api/v1/research/analyze", json={**form, "mode": "ALL"}, headers=headers
    )
    assert response.status_code == 202
    # The alternate mode has its own immutable recipe and job identity.
    all_job = container.jobs.get_job(JobId(response.json()["job_id"]))
    assert (
        all_job.spec.canonical_payload
        == service.resolve_analysis(snapshot.artifact_id, mode=ResearchMode.ALL).canonical_bytes()
    )
    # Alternate mode and malformed mode values must not reuse or mutate the first job.
    assert all_job.job_id != job.job_id
    for invalid in ("MAYBE", "all", True, None, {"mode": "ALL"}):
        assert (
            client.post(
                "/api/v1/research/analyze",
                # No coercion may turn an unsupported mode into an executable default.
                json={**form, "mode": invalid},
                headers=headers,
                # Invalid values reject before any durable queue admission.
            ).status_code
            == 422
        )
    # Legacy NON_MAYHEM fails before any job exists; explicit ALL remains a supported command.
    headers["Idempotency-Key"] = "mode-legacy"
    old_form = {"snapshot_id": legacy.artifact_id.hex}
    rejected = client.post("/api/v1/research/analyze", json=old_form, headers=headers)
    assert rejected.status_code == 422 and rejected.json()["code"] == "RESEARCH_REPREPARE_REQUIRED"
    # Explicit ALL is the only permitted new recipe over a classification-free v1 snapshot.
    assert (
        client.post(
            "/api/v1/research/analyze", json={**old_form, "mode": "ALL"}, headers=headers
        ).status_code
        # Legacy ALL admission creates a new recipe without rewriting the old snapshot.
        == 202
    )
    # Classification facts are bounded decimal-string metadata and fixed typed table rows.
    summary = client.get(f"/api/v1/research/{snapshot.artifact_id.hex}").json()
    assert summary["mode_counts"]["mayhem_rows"] == "2"
    rows = client.get(f"/api/v1/research/{snapshot.artifact_id.hex}/rows/token_modes").json()[
        "rows"
    ]
    # The fixed metadata table exposes unknown values without inferred creation coordinates.
    assert [row["mode"] for row in rows] == ["NON_MAYHEM", "MAYHEM", "UNKNOWN"]

    # The warning summary remains bounded; exact addresses are available through scoped cursors.
    assert summary["data_issue_counts"] == {
        "mints": "2",
        "non_mayhem_rows": "4",
        "mayhem_rows": "2",
    }
    endpoint = f"/api/v1/research/{snapshot.artifact_id.hex}/rows/data_issues"
    page = client.get(endpoint, params={"limit": 1}).json()
    # The continuation is tied to the same immutable warning table and cannot omit the second mint.
    next_page = client.get(endpoint, params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert page["rows"][0]["mint"] == key(5)
    assert next_page["rows"][0]["mint"] == key(6)
    assert next_page["rows"][0]["issue"] == "MISSING_CREATION_SIGNATURE"


@pytest.mark.parametrize("completed_metadata", [False, True])
def test_mode_table_shares_snapshot_output_quota(tmp_path: Path, completed_metadata: bool) -> None:
    """A quota that fits observations but not classification cannot publish half a snapshot."""

    first = LocalResearchStore(LocalArtifactRepository(tmp_path / "reference"))
    snapshot = first.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=mixed_modes
    )
    # Inspect actual output sizes to reject during the metadata table copy.
    handle = first.artifacts.open_committed(snapshot.artifact_id)
    try:
        # Use actual immutable fixture bytes to place the cap inside the second table write.
        with handle.open_binary("observations.parquet") as stream:
            quota = len(stream.read()) + 1
        # Crossing into the warning table must use the same remaining publication budget.
        if completed_metadata:
            with handle.open_binary("token_modes.parquet") as stream:
                quota += len(stream.read())
    finally:
        handle.close()
    # The independent repository has no prior successful root to mask a partial publication.
    second = LocalResearchStore(LocalArtifactRepository(tmp_path / "bounded"), output_bytes=quota)
    with pytest.raises(ResearchError, match="BYTE_LIMIT"):
        second.publish_snapshot(dataset(), DIGEST, iter((observations(),)), classify=mixed_modes)
    assert not tuple((tmp_path / "bounded").rglob("COMMITTED"))


def test_mint_cap_precedes_creation_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An oversized operand rejects locally before allowing even a bounded remote lookup."""

    monkeypatch.setattr("backtest.adapters.research.store.MAX_MODE_MINTS", 2)
    store = LocalResearchStore(LocalArtifactRepository(tmp_path))

    def forbidden(mints):
        """The source must never receive an operand that exceeds the preparation cap."""
        pytest.fail("oversized mint operand reached the source")

    # This three-mint observation set exceeds the injected local cap before collecting metadata.
    with pytest.raises(ResearchError, match="MODE_MINT_LIMIT"):
        store.publish_snapshot(dataset(), DIGEST, iter((observations(),)), classify=forbidden)
    assert not tuple(tmp_path.rglob("COMMITTED"))


# Partial creation signatures remain recorded evidence but never participate in either mode.
def incomplete_modes(mints: tuple[str, ...]) -> tuple[ResearchTokenMode, ...]:
    """Two shared tokens lack signatures; the unrelated seller remains an unknown token."""

    return tuple(
        replace(row, creation=(90, 1, 0, ""), issue="MISSING_CREATION_SIGNATURE")
        if row.creation is not None
        else row
        # Unobserved creation records retain the existing explicit UNKNOWN semantics.
        for row in mixed_modes(mints)
    )


@pytest.mark.parametrize("mode", [ResearchMode.NON_MAYHEM, ResearchMode.ALL])
def test_incomplete_tokens_skip_before_analysis_and_warn_by_mint(
    tmp_path: Path, mode: ResearchMode
) -> None:
    """All pairs disappear; exact warning pages preserve duplicate rows and source observations."""

    store = LocalResearchStore(LocalArtifactRepository(tmp_path))
    snapshot = store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=incomplete_modes
    )
    # Both token modes have incomplete records and each must be skipped before the first-buy join.
    spec = WalletAnalysisSpec(snapshot.artifact_id, DIGEST, DIGEST, mode=mode)
    result = store.analyze(spec)
    counts = {"mints": 2, "non_mayhem_rows": 4, "mayhem_rows": 2}
    # Snapshot rows remain intact; result warnings have the same complete signer scope here.
    for artifact in (snapshot, result):
        summary = store.summary(artifact.artifact_id)
        assert summary["data_issue_counts"] == counts
        assert summary["counts"]["source_rows"] == 7
        # Warning rows are paged by canonical ordinal, never an unbounded manifest list.
        first = store.page(artifact.artifact_id, ResearchTable.DATA_ISSUES, after=-1, limit=1)
        second = store.page(artifact.artifact_id, ResearchTable.DATA_ISSUES, after=0, limit=1)
        assert [first[0]["mint"], second[0]["mint"]] == [key(5), key(6)]
        # Duplicate swap rows contribute to the per-mint count exactly once per source row.
        assert first[0]["observation_rows"] == "4" and second[0]["observation_rows"] == "2"
        assert first[0]["issue"] == second[0]["issue"] == "MISSING_CREATION_SIGNATURE"
    summary = store.summary(result.artifact_id)
    # ALL retains the unrelated unknown seller; NON_MAYHEM has a valid empty selected scope.
    assert summary["counts"]["selected_rows"] == (1 if mode is ResearchMode.ALL else 0)
    assert summary["counts"]["pairs"] == summary["counts"]["evidence"] == 0
    assert store.page(result.artifact_id, ResearchTable.PAIRS, after=-1, limit=25) == ()
    # Reordering source rows and varying batches cannot change warnings or content identity.
    repeated = store.publish_snapshot(
        dataset(), DIGEST, iter((tuple(reversed(observations())),)), classify=incomplete_modes
    )
    assert repeated.artifact_id == snapshot.artifact_id
    # Signer selection limits warning counts before either token filter without omitting a defect.
    selected = store.analyze(replace(spec, wallets=(key(1),)))
    scoped = store.summary(selected.artifact_id)
    assert scoped["data_issue_counts"] == {"mints": 2, "non_mayhem_rows": 3, "mayhem_rows": 1}
    assert scoped["counts"]["selected_rows"] == 0
