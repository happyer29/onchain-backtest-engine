"""Atomic local publication of bounded benchmark evidence."""

from __future__ import annotations

from backtest.adapters.artifacts.localfs.repository import LocalArtifactRepository
from backtest.application.benchmarks import (
    BenchmarkPublication,
    BenchmarkReport,
    # Include benchmark build key so the benchmarks dependency remains explicit.
    benchmark_build_key,
)
from backtest.application.models import ArtifactDraft, ArtifactKind
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import ContentDigest


# Keep the local benchmark report publisher contract and validation rules together.
class LocalBenchmarkReportPublisher:
    def __init__(self, artifacts: LocalArtifactRepository) -> None:
        self._artifacts = artifacts

    def publish(
        self,
        # Keep the report input explicit in the publish contract.
        report: BenchmarkReport,
        attempt_nonce: ContentDigest,
    ) -> BenchmarkPublication:
        # Execute the local benchmark report publisher publish workflow in explicit,
        # reviewable steps.
        build_key = benchmark_build_key(report.spec, attempt_nonce)
        writer = self._artifacts.stage(
            ArtifactDraft(
                kind=ArtifactKind.BENCHMARK,
                build_key=build_key,
                # Pass input artifact ids explicitly so ArtifactDraft receives a
                # reviewable benchmark and input artifact ids input in local benchmark
                # report publisher publish.
                input_artifact_ids=report.spec.input_artifact_ids,
            )
        )
        try:
            # Perform the protected local benchmark report publisher publish operation
            # before explicit failure handling.
            report_bytes = canonical_json_bytes(report.document())
            with writer.open_binary("report.json") as stream:
                stream.write(report_bytes)
            manifest = {
                "attempt_nonce": attempt_nonce.hex,
                # Keep the benchmark spec id component named inside the manifest contract.
                "benchmark_spec_id": report.spec.benchmark_spec_id.hex,
                "cache_condition": report.spec.cache_condition.value,
                "capacity_days": report.spec.capacity_days,
                "capacity_model": report.spec.capacity_model.value,
                "input_artifact_ids": [item.hex for item in report.spec.input_artifact_ids],
                # Keep the launch route component named inside the manifest contract.
                "launch_route": report.spec.launch_route.value,
                "process_count": report.spec.process_count,
                "report_digest": report.report_digest.hex,
                "report_path": "report.json",
                "schema": "backtest.benchmark-artifact.v1",
                # Keep the workload component named inside the manifest contract.
                "workload": report.spec.workload.value,
            }
            committed = writer.commit(canonical_json_bytes(manifest))
        except BaseException:
            # Translate the BaseException failure through the local benchmark report
            # publisher publish boundary.
            writer.abort()
            raise
        publication = BenchmarkPublication(report, attempt_nonce, committed)
        if publication.benchmark_build_key != committed.build_key:
            raise RuntimeError("committed benchmark build key differs from the request")
        # Return the completed local benchmark report publisher publish result without a
        # hidden fallback.
        return publication


__all__ = ["LocalBenchmarkReportPublisher"]
