"""Real shared resolution, secure API, durable queue and isolated research completion."""

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Generic job submission wraps invalid semantic commands in its established public error.
from backtest.application.errors import InvalidJobPayloadError
from backtest.application.models import JobType
from backtest.application.research import ResearchError, ResearchTable
from backtest.application.use_cases.submit_job import SubmitJobRequest

# The test exercises real composition and CLI authority rather than mocked submission.
from backtest.bootstrap.cli import RuntimeCliBackend
from backtest.bootstrap.config import load_settings

# The same composition root is exercised by local CLI and server deployments.
from backtest.bootstrap.container import build_runtime_container
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId
from backtest.interfaces.api import create_app
from tests.support.research import DIGEST, configuration, dataset, observations, ordinary_modes


def test_api_queues_same_resolved_bytes_and_rejects_unsafe_queries(tmp_path: Path) -> None:
    """Public commands share local resolution and the existing secure queue boundary."""
    config = configuration(tmp_path / "profile.toml", tmp_path / "data")
    container = build_runtime_container(load_settings(config), profile="research-test")
    service = container.control.research
    assert service is not None
    # A committed hermetic snapshot is sufficient to submit analysis without source access.
    # Preparation fixtures supply immutable mode facts without contacting the source.
    snapshot = service.store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=ordinary_modes
    )
    # No source connection or native calculation is needed for typed HTTP submission.
    client = TestClient(
        create_app(container.control, control_plane_id=DIGEST), base_url="http://127.0.0.1"
    )
    assert client.get("/research").status_code == 200
    # Mutations require both a same-origin CSRF header and an explicit idempotency key.
    headers = {
        "X-Backtest-CSRF": "1",
        "Origin": "http://127.0.0.1",
        "Idempotency-Key": "research-api",
        # Raw malformed-JSON cases use the same declared media type as ordinary JSON requests.
        "Content-Type": "application/json",
    }
    # The form carries semantic research operands, not executable SQL or file locations.
    form = {
        "snapshot_id": snapshot.artifact_id.hex,
        "window_seconds": 60,
        "minimum_shared_mints": 2,
    }
    # Admission returns a durable queue record before calculation begins.
    first = client.post("/api/v1/research/analyze", json=form, headers=headers)
    assert first.status_code == 202, first.text
    # Repeating a confirmed logical command yields the same job, not a second calculation.
    again = client.post("/api/v1/research/analyze", json=form, headers=headers)
    assert again.json()["job_id"] == first.json()["job_id"]
    job_id = JobId(first.json()["job_id"])
    queued = container.jobs.get_job(job_id)
    assert queued is not None
    # Compare exact canonical bytes with the application resolver used by CLI.
    assert (
        queued.spec.canonical_payload
        == service.resolve_analysis(snapshot.artifact_id).canonical_bytes()
    )
    # Queue admission cannot legitimize arbitrary SQL or stale code/runtime operands.
    bad = client.post("/api/v1/research/analyze", json={**form, "sql": "SELECT 1"}, headers=headers)
    assert bad.status_code == 422
    # Generic submission cannot bypass installed code identity by avoiding the research form.
    stale = replace(
        service.resolve_analysis(snapshot.artifact_id), code_digest=ContentDigest("b" * 64)
    )
    # Shared research resolution identifies why the stale command is not executable.
    with pytest.raises(ResearchError, match="RERESOLVE_REQUIRED"):
        service.validate_command(stale.canonical_bytes(), prepare=False)
    # Generic queue transport preserves its existing safe error instead of admitting the job.
    request = SubmitJobRequest(
        1, JobType.ANALYZE_WALLETS, stale.canonical_bytes(), "stale-research"
    )
    with pytest.raises(InvalidJobPayloadError):
        container.control.submit_job.execute(request)
    # Only the earlier valid logical submission exists after both rejected paths.
    assert len(container.jobs.list_jobs(limit=10)) == 1
    # Ambiguous duplicate keys are rejected before the typed model can choose a winner.
    duplicate = (
        '{"snapshot_id":"' + snapshot.artifact_id.hex + '","window_seconds":1,"window_seconds":2}'
    )
    # Duplicate object keys must fail instead of choosing the first or last window value.
    assert (
        client.post("/api/v1/research/analyze", content=duplicate, headers=headers).status_code
        == 422
    )
    # Research routes inherit session CSRF and Origin checks from the existing API.
    assert client.post("/api/v1/research/analyze", json=form).status_code == 403
    foreign = client.post(
        "/api/v1/research/analyze", json=form, headers={**headers, "Origin": "https://evil.invalid"}
    )
    assert foreign.status_code == 403
    # Page quotas are checked by transport validation before opening any artifact.
    oversized = client.get(
        f"/api/v1/research/{snapshot.artifact_id.hex}/rows/observations?limit=201"
    )
    assert oversized.status_code == 422
    # Known local-source absence stays typed fail closed, with no empty snapshot substitute.
    preparation = client.post(
        "/api/v1/research/prepare", json={"from_block": 100, "to_block": 200}, headers=headers
    )
    assert preparation.status_code == 422
    assert client.get(f"/api/v1/research/jobs/{job_id.value}/result").status_code == 422
    # Cancellation uses the same durable command as every other queued job.
    cancelled = client.post(f"/api/v1/jobs/{job_id.value}/cancel", headers=headers)
    assert cancelled.status_code == 200
    # OpenAPI documents the same closed form consumed by the bounded request parser.
    schema = client.get("/api/openapi.json").json()["paths"]["/api/v1/research/analyze"]["post"]
    body_schema = schema["requestBody"]["content"]["application/json"]["schema"]
    assert body_schema["additionalProperties"] is False


def test_direct_child_receipt_result_pages_and_lineage(tmp_path: Path) -> None:
    """Run real analysis through supervisor and child, then reopen via the actual API."""

    config = configuration(tmp_path / "profile.toml", tmp_path / "data")
    container = build_runtime_container(load_settings(config), profile="research-test")
    backend = RuntimeCliBackend(container, config)
    service = backend.research_use_cases()
    # Preparation fixtures supply immutable mode facts without contacting the source.
    snapshot = service.store.publish_snapshot(
        dataset(), DIGEST, iter((observations(),)), classify=ordinary_modes
    )
    # The local source fixture has no queue job; only the immutable snapshot enters analysis.
    command = service.resolve_analysis(snapshot.artifact_id)
    result = backend.execute_research(JobType.ANALYZE_WALLETS, command.canonical_bytes())
    jobs = container.jobs.list_jobs(limit=10)
    assert len(jobs) == 1
    assert service.job_result(jobs[0].job_id) == result.artifact_id
    # Independent same-process execution reproduces the isolated child's committed bytes.
    assert service.store.analyze(command).artifact_id == result.artifact_id
    client = TestClient(
        create_app(container.control, control_plane_id=DIGEST), base_url="http://127.0.0.1"
    )
    assert client.get("/research").status_code == 200
    # Summary counters have an exact string transport representation, even at large scale.
    base = f"/api/v1/research/{result.artifact_id.hex}"
    summary = client.get(base).json()
    assert summary["counts"]["pairs"] == "1"
    # Pages contain exact decimal strings, with no Parquet URLs or raw source credentials.
    pairs = client.get(base + "/rows/pairs?limit=1").json()
    assert pairs["rows"][0]["shared_mints"] == "2"
    cursor = pairs["next_cursor"]
    assert client.get(base + f"/rows/activity?cursor={cursor}").status_code == 422
    # Drilldown resolves committed source observations for the selected pair only.
    evidence = client.get(base + "/rows/evidence?pair=0&limit=1").json()
    assert evidence["rows"][0]["delta_seconds"] == "60"
    # The result retains the precise source artifact through the standard lineage graph.
    lineage = client.get(f"/api/v1/lineage/{result.artifact_id.hex}")
    assert lineage.status_code == 200, lineage.text
    assert snapshot.artifact_id.hex in lineage.text
    assert service.page(result.artifact_id, ResearchTable.ACTIVITY)[0]["buy_rows"] == "4"
    # A result ID cannot be reused as a snapshot operand just because both are artifacts.
    with pytest.raises(ResearchError, match="EXPECTED_SNAPSHOT"):
        service.resolve_analysis(ArtifactId(result.artifact_id.hex))
