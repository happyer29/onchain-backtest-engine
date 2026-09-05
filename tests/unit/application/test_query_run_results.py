"""Focused orchestration tests for bounded Run-result queries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

# Pytest supplies controlled projection replacement without a concrete artifact.
import pytest

import backtest.application.use_cases.query_run_results as query_module
from backtest.application.ports.run_results import (
    RoundTripCursor,
    RoundTripPage,
    RunResultReaderFactory,
)

# The manifest type keeps the fake reader aligned with the application port.
from backtest.application.run_results import SuccessfulRunManifest
from backtest.application.use_cases.query_run_results import (
    PumpfunSnipingRunSummaryView,
    QueryRunResults,
    RunResultQueryError,
)

# Exact IDs are the only accepted query selector.
from backtest.domain.identifiers import ArtifactId


class _Reader:
    """Minimal verified-reader spy for application orchestration."""

    def __init__(self, page: RoundTripPage, *, failure: Exception | None = None) -> None:
        self._manifest = cast(SuccessfulRunManifest, object())
        self._page = page
        self._failure = failure
        self.verify_calls = 0
        self.page_calls: list[tuple[RoundTripCursor | None, int]] = []

    @property
    def manifest(self) -> SuccessfulRunManifest:
        return self._manifest

    def verify(self) -> None:
        self.verify_calls += 1

    def roundtrips(
        self,
        *,
        after: RoundTripCursor | None,
        limit: int,
    ) -> RoundTripPage:
        """Record the bounded page request and return its controlled outcome."""

        self.page_calls.append((after, limit))
        # Surface controlled adapter failures through the real use-case boundary.
        if self._failure is not None:
            raise self._failure
        return self._page


class _Factory:
    """Count exact-reader contexts without supplying an inter-call cache."""

    def __init__(self, reader: _Reader) -> None:
        self._reader = reader
        self.opened: list[ArtifactId] = []

    @contextmanager
    def open_exact(self, artifact_id: ArtifactId) -> Iterator[_Reader]:
        self.opened.append(artifact_id)
        yield self._reader


def test_dashboard_uses_one_reader_for_summary_and_page(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_id = ArtifactId("1" * 64)
    page = RoundTripPage((), None)
    reader = _Reader(page)
    factory = _Factory(reader)
    projected = cast(PumpfunSnipingRunSummaryView, object())

    # Isolate orchestration from the deliberately large summary field projection.
    def project(
        received_id: ArtifactId,
        manifest: SuccessfulRunManifest,
    ) -> PumpfunSnipingRunSummaryView:
        assert received_id == artifact_id
        assert manifest is reader.manifest
        return projected

    monkeypatch.setattr(query_module, "_project_sniping_summary", project)
    query = QueryRunResults(cast(RunResultReaderFactory, factory))
    result = query.dashboard(artifact_id, limit=25)

    # Only one exact-reader context may serve both dashboard projections.
    assert factory.opened == [artifact_id]
    assert reader.page_calls == [(None, 25)]
    assert reader.verify_calls == 1
    # Both projections originate from the same reader lifetime.
    assert result.summary is projected
    assert result.roundtrips is page


def test_dashboard_preserves_safe_result_failure_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_id = ArtifactId("2" * 64)
    reader = _Reader(RoundTripPage((), None), failure=ValueError("unsafe detail"))
    factory = _Factory(reader)
    projected = cast(PumpfunSnipingRunSummaryView, object())

    # Let the page failure cross the same projection path as a successful dashboard.
    monkeypatch.setattr(
        query_module,
        "_project_sniping_summary",
        lambda received_id, manifest: projected,
    )
    query = QueryRunResults(cast(RunResultReaderFactory, factory))
    with pytest.raises(RunResultQueryError, match="RUN_RESULT_UNAVAILABLE") as raised:
        query.dashboard(artifact_id, limit=25)

    # The wrapped error exposes no adapter detail and does not invoke verification later.
    assert raised.value.code == "RUN_RESULT_UNAVAILABLE"
    assert factory.opened == [artifact_id]
    assert reader.verify_calls == 0


def test_dashboard_rejects_unbounded_page_before_opening_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader(RoundTripPage((), None))
    factory = _Factory(reader)
    query = QueryRunResults(cast(RunResultReaderFactory, factory))

    # A malformed limit must not authenticate or touch any artifact.
    monkeypatch.setattr(query_module, "MAX_ROUNDTRIP_PAGE_SIZE", 200)
    with pytest.raises(ValueError, match="between 1 and 200"):
        query.dashboard(ArtifactId("3" * 64), limit=201)
    assert factory.opened == []
