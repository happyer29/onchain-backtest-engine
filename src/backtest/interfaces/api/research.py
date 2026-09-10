"""Typed same-origin research commands and bounded immutable table views."""

from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

# The transport calls application use cases and has no data, SQL or filesystem adapter.
from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.models import JobType
from backtest.application.research import ResearchError, ResearchTable
from backtest.application.research_pages import cursor_after, page_cursor
from backtest.application.use_cases.research import ResearchUseCases

# Shared job submission preserves existing idempotency and queue authority.
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.identifiers import ArtifactId, JobId
from backtest.interfaces.api.ml_schemas import DigestText
from backtest.interfaces.api.schemas import JobResponse


class ResearchModel(BaseModel):
    """Reject arbitrary command fields and type coercions at the public boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PrepareResearchForm(ResearchModel):
    """Only authoritative block bounds are user-provided acquisition operands."""

    from_block: int = Field(ge=0, lt=2**32)
    to_block: int = Field(gt=0, le=2**32)


class AnalyzeWalletsForm(ResearchModel):
    """The recipe exposes semantic filters and a single immutable snapshot identity."""

    snapshot_id: DigestText
    window_seconds: int = Field(default=60, ge=0, le=3600)
    minimum_shared_mints: int = Field(default=2, ge=1, le=2_000_000)
    # Public keys are bounded here and fully decoded by the application contract.
    wallets: list[Annotated[str, Field(min_length=32, max_length=44)]] = Field(
        default_factory=list,
        max_length=128,
    )


class ResearchRows(ResearchModel):
    """Each response contains one bounded view and its exclusive continuation."""

    artifact_id: str
    table: str
    rows: tuple[dict[str, str], ...]
    next_cursor: str | None


def _body_schema(model: type[ResearchModel]) -> dict[str, object]:
    """Expose the typed form in OpenAPI while retaining the bounded streaming parser."""

    content = {"application/json": {"schema": model.model_json_schema()}}
    return {"requestBody": {"required": True, "content": content}}


# The bounded-body reader is injected from the same application security boundary.
def research_router(
    service: ResearchUseCases | None,
    submitter: SubmitJob,
    maximum_bytes: int,
    # This callback only validates transport bytes; it never resolves or executes a job.
    read_body: Callable[[Request, int], Awaitable[bytes]],
) -> APIRouter:
    """Heavy commands only enqueue; GETs read verified metadata and bounded row groups."""

    router = APIRouter(prefix="/api/v1/research", tags=["research"])

    def required() -> ResearchUseCases:
        """Reduced compositions must reject research rather than fabricate empty output."""
        if service is None:
            raise HTTPException(status_code=503, detail="RESEARCH_UNAVAILABLE")
        return service

    def submit(request: Request, response: Response, kind: JobType, payload: bytes) -> JobResponse:
        """Use the same idempotency and exact-input queue boundary as every other command."""

        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1:
            raise HTTPException(status_code=422, detail="IDEMPOTENCY_KEY_REQUIRED")
        record = submitter.execute(SubmitJobRequest(1, kind, payload, keys[0]))
        # Report the durable job identity; this request has not performed the heavy work.
        response.headers["Location"] = f"/api/v1/jobs/{record.job_id.value}"
        return JobResponse.from_domain(record)

    # Preparation accepts a closed block-range form; source details come from composition.
    @router.post(
        "/prepare",
        status_code=202,
        response_model=JobResponse,
        # OpenAPI documents the form without replacing the bounded streaming parser.
        openapi_extra=_body_schema(PrepareResearchForm),
    )
    async def prepare(request: Request, response: Response) -> JobResponse:
        """Materialize installed acquisition operands before durable submission."""

        raw = await read_body(request, maximum_bytes)
        try:
            form = PrepareResearchForm.model_validate_json(canonicalize_job_payload(raw))
        except ValueError:
            raise HTTPException(status_code=422, detail="RESEARCH_INVALID_FORM") from None
        # Validation follows the bounded stream read, never an eager unbounded body parse.
        command = required().resolve_prepare(form.from_block, form.to_block)
        return submit(request, response, JobType.PREPARE_RESEARCH, command.canonical_bytes())

    # Analysis queues a fixed local recipe rather than running DuckDB in the request.
    @router.post(
        "/analyze",
        status_code=202,
        response_model=JobResponse,
        # The schema is generated from the same strict model used below.
        openapi_extra=_body_schema(AnalyzeWalletsForm),
    )
    async def analyze(request: Request, response: Response) -> JobResponse:
        """Resolve the exact local snapshot and fixed recipe, never a user-provided query."""

        raw = await read_body(request, maximum_bytes)
        try:
            form = AnalyzeWalletsForm.model_validate_json(canonicalize_job_payload(raw))
        except ValueError:
            raise HTTPException(status_code=422, detail="RESEARCH_INVALID_FORM") from None
        # The same application resolver is called by the CLI before direct execution.
        command = required().resolve_analysis(
            ArtifactId(form.snapshot_id),
            window_seconds=form.window_seconds,
            minimum_shared_mints=form.minimum_shared_mints,
            # Full address validation and canonical selection ordering belong to the use case.
            wallets=tuple(form.wallets),
        )
        # Canonical bytes cross the shared queue boundary, exactly as for CLI execution.
        return submit(request, response, JobType.ANALYZE_WALLETS, command.canonical_bytes())

    @router.get("/{artifact_id}")
    def summary(request: Request, artifact_id: DigestText) -> dict[str, object]:
        """Map verified manifests into useful display fields without exposing file paths."""

        if request.query_params:
            raise ResearchError("RESEARCH_INVALID_QUERY")
        document = required().summary(ArtifactId(artifact_id))
        dataset = cast(dict[str, object], document["dataset"])
        # Dataset metadata is already validated against the closed immutable manifest schema.
        counts = cast(dict[str, int], document["counts"])
        return {
            "artifact_id": artifact_id,
            "kind": document["kind"],
            "dataset": dataset,
            # All aggregate integers cross the browser boundary as decimal strings.
            "counts": {key: str(value) for key, value in counts.items()},
            "quality": document["quality"],
            "analysis": document.get("analysis"),
        }

    # Successful job navigation still authenticates the exact committed result manifest.
    @router.get("/jobs/{job_id}/result")
    def job_result(job_id: str) -> dict[str, str]:
        """Let a completed preparation or analysis navigate to its verified output."""

        return {"artifact_id": required().job_result(JobId(job_id)).hex}

    # Only fixed table roles and scoped opaque cursors are accepted by the row endpoint.
    @router.get("/{artifact_id}/rows/{table}", response_model=ResearchRows)
    def rows(
        request: Request,
        artifact_id: DigestText,
        table: ResearchTable,
        # Continuations remain bound to this artifact, table and selected evidence pair.
        cursor: Annotated[str | None, Query(max_length=1024)] = None,
        # Request quotas apply before the application opens any columnar reader.
        limit: Annotated[int, Query(ge=1, le=200)] = 25,
        pair: Annotated[int | None, Query(ge=0, le=2_000_000)] = None,
    ) -> ResearchRows:
        """A graph or evidence table is one explicitly labelled page of a complete result."""

        allowed = {"cursor", "limit", "pair"}
        if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            raise ResearchError("RESEARCH_INVALID_QUERY")
        # Cursor scope is checked before any artifact reader is opened.
        artifact = ArtifactId(artifact_id)
        after = cursor_after(cursor, artifact, table, pair)
        values = required().page(artifact, table, after=after, limit=limit, pair=pair)
        next_cursor = None
        # A full page can continue; an empty final continuation is harmless and bounded.
        if values and len(values) == limit:
            next_cursor = page_cursor(artifact, table, pair, int(values[-1]["row_id"]))
        # Serialized response limits bound evidence enrichment as well as ordinary rows.
        result = ResearchRows(
            artifact_id=artifact_id, table=table.value, rows=values, next_cursor=next_cursor
        )
        if len(result.model_dump_json().encode("utf-8")) > maximum_bytes:
            raise HTTPException(status_code=413, detail="RESEARCH_RESPONSE_LIMIT")
        # No response can exceed the same configured transport envelope as command requests.
        return result

    return router
