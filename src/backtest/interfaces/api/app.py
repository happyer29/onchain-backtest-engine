"""FastAPI inbound adapter for the single-host control plane."""

from __future__ import annotations

import hmac
import logging
import re
import secrets

# Import time at the visible module dependency boundary.
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# Import typing at the visible module dependency boundary.
from typing import Annotated, Final
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

# Import staticfiles at the visible module dependency boundary.
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import RequestResponseEndpoint

from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.errors import (
    # Include application error so the errors dependency remains explicit.
    ApplicationError,
    ErrorCode,
    InvalidIdempotencyKeyError,
    InvalidJobPayloadError,
)

# Import job commands at the visible module dependency boundary.
from backtest.application.job_commands import ResolvedBacktestJob
from backtest.application.ml_job_commands import MlResolvedJob
from backtest.application.ml_reference import ReferenceMlContract
from backtest.application.models import (
    AttemptState,
    # Include job type so the models dependency remains explicit.
    JobType,
    ListJobEventsRequest,
)
from backtest.application.ports.catalog import RunListCursor
from backtest.application.ports.jobs import JobListCursor
from backtest.application.ports.run_results import RoundTripCursor

# Import system at the visible module dependency boundary.
from backtest.application.ports.system import SystemResourceProbe
from backtest.application.run_contracts import QueryRunContracts
from backtest.application.run_results import RunPhysicalSettings
from backtest.application.use_cases.cancel_job import CancelJob, CancelJobRequest
from backtest.application.use_cases.inspect_source import InspectSourceRequest

# Import plan dataset at the visible module dependency boundary.
from backtest.application.use_cases.plan_dataset import PlanDataset
from backtest.application.use_cases.query_artifacts import ArtifactQueryError, QueryArtifacts
from backtest.application.use_cases.query_job_events import ListJobEvents
from backtest.application.use_cases.query_jobs import GetJob, GetJobRequest, ListJobs
from backtest.application.use_cases.query_run_results import QueryRunResults, RunResultQueryError

# Import query runs at the visible module dependency boundary.
from backtest.application.use_cases.query_runs import QueryRuns, RunIndexQueryError
from backtest.application.use_cases.resolve_run_spec import ResolveRunSpec
from backtest.application.use_cases.resolve_sweep_spec import ResolveSweepSpec
from backtest.application.use_cases.retry_job import RetryJob, RetryJobRequest
from backtest.application.use_cases.store_source_inspection import StoreSourceInspection

# Import submit job at the visible module dependency boundary.
from backtest.application.use_cases.submit_job import SubmitJob, SubmitJobRequest
from backtest.domain.identifiers import ArtifactId, ContentDigest, JobId, LogicalRunId, SourceId
from backtest.interfaces.api.ml_schemas import (
    BuildFeaturesJobForm,
    BuildLabelsJobForm,
    # Include build model schedule job form so the ml schemas dependency remains explicit.
    BuildModelScheduleJobForm,
    BuildUniverseJobForm,
    MlApiModel,
    PredictJobForm,
    TrainModelJobForm,
    # Close the ml schemas import after its required symbols are visible.
)
from backtest.interfaces.api.pagination import (
    PAGE_TOKEN_PATTERN,
    PageTokenError,
    decode_job_cursor,
    decode_run_cursor,
    # Encoders issue opaque continuations only from validated application keys.
    encode_job_cursor,
    encode_run_cursor,
)
from backtest.interfaces.api.schemas import (
    ArtifactDetailsResponse,
    ArtifactLineageResponse,
    DatasetPlanResponse,
    # Include error response so the schemas dependency remains explicit.
    ErrorResponse,
    HealthResponse,
    JobCommand,
    JobEventListResponse,
    JobEventResponse,
    # Include job list response so the schemas dependency remains explicit.
    JobListResponse,
    JobResponse,
    PlanDatasetCommand,
    PumpfunSnipingDashboardResponse,
    PumpfunSnipingRunSummaryResponse,
    ReferenceMlContractResponse,
    # Include reference sweep draft command so the schemas dependency remains explicit.
    ReferenceSweepDraftCommand,
    ResolvedRunSpecResponse,
    ResolvedSweepSpecResponse,
    RoundTripPageResponse,
    RunBacktestCommand,
    # Include run contract list response so the schemas dependency remains explicit.
    RunContractListResponse,
    RunContractResponse,
    RunDraftCommand,
    RunListResponse,
    RunPhysicalSettingsCommand,
    # Include run summary response so the schemas dependency remains explicit.
    RunSummaryResponse,
    SourceInspectionResponse,
    SystemResourcesResponse,
    run_draft_command_from_bytes,
)

# Bind terminal to status once as an explicit module-level contract.
_TERMINAL_TO_STATUS: Final = {
    ErrorCode.JOB_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.IDEMPOTENCY_CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.JOB_STATE_CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.LOCAL_STATE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    # Keep the error code component named inside the terminal to status contract.
    ErrorCode.SOURCE_INSPECTION_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.PROFILE_INVALID: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.REQUEST_IDENTITY_MISMATCH: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.SOURCE_READ_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.NORMALIZATION_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.INCOMPLETE_BLOCK_RANGE: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.TRANSACTION_CLOCK_MISMATCH: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.BUNDLED_BUY_CONTRACT_MISMATCH: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.CURVE_TRANSITION_MISMATCH: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.LIFECYCLE_CONTRACT_MISMATCH: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.WORKFLOW_NOT_IMPLEMENTED: status.HTTP_501_NOT_IMPLEMENTED,
}
_SESSION_COOKIE: Final = "backtest_session"
_SESSION_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]{32,512}")
# Bind audit log once as an explicit module-level contract.
_AUDIT_LOG = logging.getLogger("backtest.control.audit")


# Keep the control use cases contract and validation rules together.
@dataclass(frozen=True, slots=True)
class ControlUseCases:
    inspect_source: StoreSourceInspection
    plan_dataset: PlanDataset
    submit_job: SubmitJob
    # Declare cancel job explicitly in the control use cases contract.
    cancel_job: CancelJob
    get_job: GetJob
    list_jobs: ListJobs
    profile: str
    default_run_physical_settings: RunPhysicalSettings
    # Declare query artifacts explicitly in the control use cases contract.
    query_artifacts: QueryArtifacts | None = None
    query_runs: QueryRuns | None = None
    system_resources: SystemResourceProbe | None = None
    resolve_run_spec: ResolveRunSpec | None = None
    resolve_sweep_spec: ResolveSweepSpec | None = None
    # Declare retry job explicitly in the control use cases contract.
    retry_job: RetryJob | None = None
    list_job_events: ListJobEvents | None = None
    ml_reference_contract: ReferenceMlContract | None = None
    query_run_contracts: QueryRunContracts | None = None
    query_run_results: QueryRunResults | None = None


# Define create app as one focused operation with an explicit boundary.
def create_app(
    use_cases: ControlUseCases,
    *,
    control_plane_id: ContentDigest,
    max_request_bytes: int = 2 * 1024 * 1024,
    # Keep the allowed hosts input explicit in the create app contract.
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "::1", "localhost"),
    enforce_session: bool = True,
    session_token: str | None = None,
    secure_cookie: bool = False,
    write_rate_limit_per_minute: int = 120,
    # Keep the fast api input explicit in the create app contract.
) -> FastAPI:
    # Execute the create app workflow in explicit, reviewable steps.
    if max_request_bytes <= 0:
        raise ValueError("max_request_bytes must be positive")
    normalized_hosts = frozenset(_normalize_host(value) for value in allowed_hosts)
    if not normalized_hosts:
        raise ValueError("allowed_hosts must not be empty")
    # Guard this path with write_rate_limit_per_minute <= 0 before applying effects.
    if write_rate_limit_per_minute <= 0:
        raise ValueError("write_rate_limit_per_minute must be positive")
    selected_session_token = session_token or secrets.token_urlsafe(32)
    if _SESSION_TOKEN.fullmatch(selected_session_token) is None:
        raise ValueError("session token must use the bounded URL-safe alphabet")
    # Assemble write limiter once so the create app workflow shares one value.
    write_limiter = _LocalWriteRateLimiter(write_rate_limit_per_minute)

    app = FastAPI(
        title="On-Chain Backtest Engine Control API",
        version="1",
        docs_url=None,
        # Pass redoc url explicitly so FastAPI receives a reviewable control API
        # control api and 1 input in create app.
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    static_root = Path(__file__).parent.parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_root, check_dir=True), name="static")

    # Apply middleware semantics to the following security headers contract.
    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Execute the security headers workflow in explicit, reviewable steps.
        try:
            request_host = _normalize_host(request.url.hostname or "")
        except ValueError:
            request_host = ""
        if request_host not in normalized_hosts:
            # Handle the security headers request_host not in normalized_hosts branch as a
            # distinct logical block.
            return _secured_response(
                _error_response(
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_HOST",
                    "Request Host is not allowed by the local control plane.",
                    # Complete _error_response only after its invalid host and value inputs
                    # are visible in security headers.
                ),
                api=request.url.path.startswith("/api/"),
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin_request(request):
            # Handle the security headers method, request and get condition as a distinct
            # block.
            return _secured_response(
                _error_response(
                    status.HTTP_403_FORBIDDEN,
                    "FORBIDDEN_ORIGIN",
                    "Cross-origin mutation is not allowed.",
                    # Complete _error_response only after its forbidden origin and value
                    # inputs are visible in security headers.
                ),
                api=request.url.path.startswith("/api/"),
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith(
            "/api/"
            # Complete startswith only after its /api/ inputs are visible in security headers.
        ):
            # Handle the security headers method, startswith and request condition as a
            # distinct block.
            if not write_limiter.allow(request.client.host if request.client else "local"):
                # Handle the security headers allow, write limiter and client condition as
                # a distinct block.
                return _secured_response(
                    _error_response(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "WRITE_RATE_LIMITED",
                        "Too many local state-changing requests.",
                        # Complete _error_response only after its write rate limited and value
                        # inputs are visible in security headers.
                    ),
                    api=True,
                )
            if enforce_session and not _valid_mutation_session(
                request,
                # Pass selected session token explicitly so _valid_mutation_session
                # receives a reviewable request and selected session token input in
                # security headers.
                selected_session_token,
            ):
                # Handle the security headers enforce session, valid mutation session and
                # request condition as a distinct block.
                return _secured_response(
                    _error_response(
                        status.HTTP_403_FORBIDDEN,
                        "INVALID_SESSION",
                        "A same-origin local session and CSRF header are required.",
                        # Complete _error_response only after its invalid session and value
                        # inputs are visible in security headers.
                    ),
                    api=True,
                )
        response = await call_next(request)
        return _secured_response(response, api=request.url.path.startswith("/api/"))

    # Apply exception handler semantics to the following application error handler
    # contract.
    @app.exception_handler(ApplicationError)
    async def application_error_handler(_: Request, error: ApplicationError) -> JSONResponse:
        # Execute the application error handler workflow in explicit, reviewable steps.
        return JSONResponse(
            status_code=_TERMINAL_TO_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
            content=ErrorResponse(code=error.code.value, message=error.safe_message).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    # Define validation error handler as one focused operation with an explicit boundary.
    async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
        # Execute the validation error handler workflow in explicit, reviewable steps.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=ErrorResponse(
                code="VALIDATION_ERROR",
                message="Request does not match the versioned API schema.",
                # Complete model_dump only after its declared inputs are visible in validation
                # error handler.
            ).model_dump(),
        )

    @app.exception_handler(ArtifactQueryError)
    async def artifact_query_error_handler(_: Request, __: ArtifactQueryError) -> JSONResponse:
        # Execute the artifact query error handler workflow in explicit, reviewable steps.
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                code="ARTIFACT_NOT_FOUND",
                message="The requested verified artifact metadata is unavailable.",
                # Complete model_dump only after its declared inputs are visible in artifact
                # query error handler.
            ).model_dump(),
        )

    @app.exception_handler(RunIndexQueryError)
    async def run_index_query_error_handler(_: Request, error: RunIndexQueryError) -> JSONResponse:
        """Expose rebuildable-index failure separately from an absent artifact."""

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                code=error.code,
                message="The verified Run ordering index is unavailable and must be rebuilt.",
            ).model_dump(),
        )

    @app.exception_handler(RunResultQueryError)
    async def run_result_query_error_handler(
        _: Request,
        # Keep the error input explicit in the run result query error handler contract.
        error: RunResultQueryError,
    ) -> JSONResponse:
        # Execute the run result query error handler workflow in explicit, reviewable
        # steps.
        response = {
            "RUN_HAS_NO_PUMPFUN_SNIPING_RESULTS": (
                status.HTTP_409_CONFLICT,
                "The exact Run artifact does not contain Pump.fun Sniping results.",
            ),
            # Keep the run result unavailable component named inside the response
            # contract.
            "RUN_RESULT_UNAVAILABLE": (
                status.HTTP_404_NOT_FOUND,
                "The requested verified Run result is unavailable.",
            ),
        }[error.code]
        # Return the completed run result query error handler result without a hidden
        # fallback.
        return JSONResponse(
            status_code=response[0],
            content=ErrorResponse(code=error.code, message=response[1]).model_dump(),
        )

    @app.exception_handler(HTTPException)
    # Define http error handler as one focused operation with an explicit boundary.
    async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
        # Execute the http error handler workflow in explicit, reviewable steps.
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                code=_http_error_code(error.status_code),
                message=_http_error_message(error.status_code),
                # Complete model_dump only after its declared inputs are visible in http error
                # handler.
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
        # Execute the unexpected error handler workflow in explicit, reviewable steps.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                code="INTERNAL_ERROR",
                message="The local control plane could not complete the request.",
                # Complete model_dump only after its declared inputs are visible in unexpected
                # error handler.
            ).model_dump(),
        )

    @app.get("/", include_in_schema=False)
    async def web_ui() -> FileResponse:
        # Execute the web ui workflow in explicit, reviewable steps.
        return _web_page_response(
            static_root / "index.html",
            enforce_session=enforce_session,
            session_token=selected_session_token,
            secure_cookie=secure_cookie,
        )

    @app.get("/sniping-results", include_in_schema=False)
    async def sniping_results_dashboard() -> FileResponse:
        """Serve the bounded Pump.fun Sniping result dashboard."""

        return _web_page_response(
            static_root / "sniping-results.html",
            enforce_session=enforce_session,
            session_token=selected_session_token,
            secure_cookie=secure_cookie,
        )

    @app.get("/api/v1/health", response_model=HealthResponse)
    # Define health as one focused operation with an explicit boundary.
    async def health() -> HealthResponse:
        # Execute the health workflow in explicit, reviewable steps.
        return HealthResponse(
            status="ok",
            profile=use_cases.profile,
            version=_package_version(),
            control_plane_id=control_plane_id.hex,
            # Complete HealthResponse only after its ok and profile inputs are visible in
            # health.
        )

    app.add_api_route(
        "/api/v1/system/health",
        health,
        methods=["GET"],
        # Pass response model explicitly so add_api_route receives a reviewable
        # /api/v1/system/health and get input in create app.
        response_model=HealthResponse,
        include_in_schema=False,
    )

    @app.post(
        "/api/v1/sources/{source_id}/inspect",
        # Pass response model explicitly so post receives a reviewable
        # /api/v1/sources/{source id}/inspect and source inspection response input in
        # inspect source.
        response_model=SourceInspectionResponse,
    )
    async def inspect_source(source_id: str) -> SourceInspectionResponse:
        # Execute the inspect source workflow in explicit, reviewable steps.
        stored = use_cases.inspect_source.execute(InspectSourceRequest(_source_id(source_id)))
        return SourceInspectionResponse.from_stored(stored)

    @app.post("/api/v1/datasets/plan", response_model=DatasetPlanResponse)
    async def plan_dataset(request: Request) -> DatasetPlanResponse:
        # Execute the plan dataset workflow in explicit, reviewable steps.
        raw = await _bounded_json_body(request, max_request_bytes)
        command = _parse_plan_command(raw)
        try:
            domain_request = command.to_domain()
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the plan dataset
            # boundary.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error
        return _bounded_api_response(
            DatasetPlanResponse.from_domain(use_cases.plan_dataset.execute(domain_request)),
            # Pass max request bytes explicitly so _bounded_api_response receives a
            # reviewable from domain and execute input in plan dataset.
            max_request_bytes,
        )

    @app.post("/api/v1/run-specs/resolve", response_model=ResolvedRunSpecResponse)
    async def resolve_run_spec(request: Request) -> ResolvedRunSpecResponse:
        # Execute the resolve run spec workflow in explicit, reviewable steps.
        raw = await _bounded_json_body(request, max_request_bytes)
        command = _parse_run_draft(raw)
        resolver = _required_service(use_cases.resolve_run_spec)
        try:
            resolved = resolver.execute(command.to_domain())
        # Translate type error through the resolve run spec boundary without hiding other
        # errors.
        except (TypeError, ValueError, RuntimeError) as error:
            # Translate the (TypeError, ValueError, RuntimeError) failure through the
            # resolve run spec boundary.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error
        return _bounded_api_response(
            ResolvedRunSpecResponse.from_domain(resolved),
            # Pass max request bytes explicitly so _bounded_api_response receives a
            # reviewable from domain and resolved input in resolve run spec.
            max_request_bytes,
        )

    @app.get(
        "/api/v1/run-physical-settings",
        response_model=RunPhysicalSettingsCommand,
        # Complete get only after its /api/v1/run-physical-settings and run physical settings
        # command inputs are visible in default run physical settings.
    )
    async def default_run_physical_settings() -> RunPhysicalSettingsCommand:
        return RunPhysicalSettingsCommand.from_domain(use_cases.default_run_physical_settings)

    @app.get("/api/v1/run-contracts", response_model=RunContractListResponse)
    async def run_contracts() -> RunContractListResponse:
        # Execute the run contracts workflow in explicit, reviewable steps.
        contracts = _required_service(use_cases.query_run_contracts)
        return _bounded_api_response(
            RunContractListResponse(
                items=tuple(RunContractResponse.from_domain(item) for item in contracts.list())
            ),
            # Pass max request bytes explicitly so _bounded_api_response receives a
            # reviewable from domain and list input in run contracts.
            max_request_bytes,
        )

    @app.post(
        "/api/v1/backtests",
        response_model=JobResponse,
        # Pass status code explicitly so post receives a reviewable /api/v1/backtests and
        # http 202 accepted input in submit backtest.
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_backtest(request: Request, response: Response) -> JobResponse:
        # Execute the submit backtest workflow in explicit, reviewable steps.
        form = _parse_run_backtest_command(await _bounded_json_body(request, max_request_bytes))
        try:
            command = form.to_domain()
        except (TypeError, ValueError) as error:
            # Translate the (TypeError, ValueError) failure through the submit backtest
            # boundary.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error
        if command.physical_settings.threads != use_cases.default_run_physical_settings.threads:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
        # Return the completed submit backtest result without a hidden fallback.
        return _submit_backtest_job(use_cases.submit_job, request, response, command)

    @app.post("/api/v1/sweep-specs/resolve", response_model=ResolvedSweepSpecResponse)
    async def resolve_sweep_spec(request: Request) -> ResolvedSweepSpecResponse:
        # Execute the resolve sweep spec workflow in explicit, reviewable steps.
        raw = await _bounded_json_body(request, max_request_bytes)
        command = _parse_sweep_draft(raw)
        resolver = _required_service(use_cases.resolve_sweep_spec)
        try:
            # Perform the protected resolve sweep spec operation before explicit failure
            # handling.
            entries = tuple(item.to_domain() for item in command.entries)
            if any(
                item.physical_settings.threads != use_cases.default_run_physical_settings.threads
                for item in entries
            ):
                # Fail the resolve sweep spec path with ValueError for sweep threads
                # differ from the configured host profile when threads, item and entries
                # is true; do not continue ambiguously.
                raise ValueError("sweep threads differ from the configured host profile")
            resolved = resolver.execute(
                entries,
                comparison_metrics=command.comparison_metrics,
            )
        # Translate type error through the resolve sweep spec boundary without hiding
        # other errors.
        except (TypeError, ValueError, RuntimeError) as error:
            # Translate the (TypeError, ValueError, RuntimeError) failure through the
            # resolve sweep spec boundary.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from error
        return _bounded_api_response(
            ResolvedSweepSpecResponse.from_domain(resolved),
            # Pass max request bytes explicitly so _bounded_api_response receives a
            # reviewable from domain and resolved input in resolve sweep spec.
            max_request_bytes,
        )

    @app.post(
        "/api/v1/jobs",
        response_model=JobResponse,
        # Pass status code explicitly so post receives a reviewable /api/v1/jobs and http
        # 202 accepted input in submit job.
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_job(
        request: Request,
        response: Response,
        # Keep the job response input explicit in the submit job contract.
    ) -> JobResponse:
        # Execute the submit job workflow in explicit, reviewable steps.
        idempotency_keys = request.headers.getlist("idempotency-key")
        if len(idempotency_keys) != 1:
            raise InvalidIdempotencyKeyError
        raw = await _bounded_json_body(request, max_request_bytes)
        command = _parse_job_command(raw)
        # Assemble record once so the submit job workflow shares one value.
        record = use_cases.submit_job.execute(
            SubmitJobRequest(
                spec_version=command.spec_version,
                job_type=command.job_type,
                payload_json=command.payload_bytes(),
                # Pass idempotency key explicitly so SubmitJobRequest receives a
                # reviewable spec version and job type input in submit job.
                idempotency_key=idempotency_keys[0],
                input_artifact_ids=command.artifact_ids(),
            )
        )
        response.headers["Location"] = f"/api/v1/jobs/{record.job_id.value}"
        # Invoke info for job created job id=%s job type=%s and value as a visible submit
        # job step.
        _AUDIT_LOG.info(
            "job_created job_id=%s job_type=%s", record.job_id.value, record.spec.job_type
        )
        return JobResponse.from_domain(record)

    @app.post(
        # Pass api v1 ml features explicitly so post receives a reviewable
        # /api/v1/ml/features and http 202 accepted input in build features.
        "/api/v1/ml/features",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def build_features(request: Request, response: Response) -> JobResponse:
        # Execute the build features workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            BuildFeaturesJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and build features input in build features.
            use_cases.submit_job,
            request,
            response,
            JobType.BUILD_FEATURES,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and build features inputs are
            # visible in build features.
        )

    @app.post(
        "/api/v1/ml/universes",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        # Complete post only after its /api/v1/ml/universes and http 202 accepted inputs are
        # visible in build universe.
    )
    async def build_universe(request: Request, response: Response) -> JobResponse:
        # Execute the build universe workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            BuildUniverseJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and build universe input in build universe.
            use_cases.submit_job,
            request,
            response,
            JobType.BUILD_UNIVERSE,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and build universe inputs are
            # visible in build universe.
        )

    @app.post(
        "/api/v1/ml/labels",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        # Complete post only after its /api/v1/ml/labels and http 202 accepted inputs are
        # visible in build labels.
    )
    async def build_labels(request: Request, response: Response) -> JobResponse:
        # Execute the build labels workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            BuildLabelsJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and build labels input in build labels.
            use_cases.submit_job,
            request,
            response,
            JobType.BUILD_LABELS,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and build labels inputs are
            # visible in build labels.
        )

    @app.post(
        "/api/v1/ml/models/train",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        # Complete post only after its /api/v1/ml/models/train and http 202 accepted inputs
        # are visible in train model.
    )
    async def train_model(request: Request, response: Response) -> JobResponse:
        # Execute the train model workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            TrainModelJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and train model input in train model.
            use_cases.submit_job,
            request,
            response,
            JobType.TRAIN_MODEL,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and train model inputs are
            # visible in train model.
        )

    @app.post(
        "/api/v1/ml/model-schedules",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        # Complete post only after its /api/v1/ml/model-schedules and http 202 accepted inputs
        # are visible in build model schedule.
    )
    async def build_model_schedule(request: Request, response: Response) -> JobResponse:
        # Execute the build model schedule workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            BuildModelScheduleJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and build model schedule input in build model schedule.
            use_cases.submit_job,
            request,
            response,
            JobType.BUILD_MODEL_SCHEDULE,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and build model schedule
            # inputs are visible in build model schedule.
        )

    @app.post(
        "/api/v1/ml/predictions",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        # Complete post only after its /api/v1/ml/predictions and http 202 accepted inputs are
        # visible in predict.
    )
    async def predict(request: Request, response: Response) -> JobResponse:
        # Execute the predict workflow in explicit, reviewable steps.
        form = _parse_ml_form(
            await _bounded_json_body(request, max_request_bytes),
            PredictJobForm,
        )
        return _submit_ml_job(
            # Pass use cases explicitly so _submit_ml_job receives a reviewable submit job
            # and predict input in predict.
            use_cases.submit_job,
            request,
            response,
            JobType.PREDICT,
            form.to_domain(),
            # Complete _submit_ml_job only after its submit job and predict inputs are visible
            # in predict.
        )

    @app.get("/api/v1/jobs", response_model=JobListResponse)
    def list_jobs(
        request: Request,
        state_filter: Annotated[AttemptState | None, Query(alias="state")] = None,
        limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
        # Offset is a bounded compatibility path; browser arrows use cursor.
        offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
        cursor: Annotated[
            str | None,
            Query(min_length=1, max_length=512, pattern=PAGE_TOKEN_PATTERN),
        ] = None,
    ) -> JobListResponse:
        # Execute the list jobs workflow in explicit, reviewable steps.
        _require_exact_query_parameters(
            request,
            allowed=frozenset({"cursor", "limit", "offset", "state"}),
        )
        page = use_cases.list_jobs.page(
            state=state_filter,
            limit=limit,
            offset=offset,
            after=_job_list_cursor(cursor, state=state_filter, offset=offset),
        )
        return JobListResponse(
            items=tuple(JobResponse.from_domain(item) for item in page.items),
            next_cursor=(None if page.next_cursor is None else encode_job_cursor(page.next_cursor)),
        )

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    # Define get job as one focused operation with an explicit boundary.
    def get_job(job_id: str) -> JobResponse:
        # Execute the get job workflow in explicit, reviewable steps.
        record = use_cases.get_job.execute(GetJobRequest(_job_id(job_id)))
        return JobResponse.from_domain(record)

    @app.get("/api/v1/jobs/{job_id}/events", response_model=JobEventListResponse)
    def list_job_events(
        job_id: str,
        # Keep the after event id input explicit in the list job events contract.
        after_event_id: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=1_000)] = 200,
    ) -> JobEventListResponse:
        # Execute the list job events workflow in explicit, reviewable steps.
        query = _required_service(use_cases.list_job_events)
        records = query.execute(ListJobEventsRequest(_job_id(job_id), after_event_id, limit))
        return JobEventListResponse(
            items=tuple(JobEventResponse.from_domain(item) for item in records)
        )

    # Apply get semantics to the following artifact details contract.
    @app.get("/api/v1/artifacts/{artifact_id}", response_model=ArtifactDetailsResponse)
    def artifact_details(artifact_id: str) -> ArtifactDetailsResponse:
        # Execute the artifact details workflow in explicit, reviewable steps.
        queries = _required_service(use_cases.query_artifacts)
        return ArtifactDetailsResponse.from_domain(queries.details(_artifact_id(artifact_id)))

    @app.get("/api/v1/lineage/{artifact_id}", response_model=ArtifactLineageResponse)
    def artifact_lineage(artifact_id: str) -> ArtifactLineageResponse:
        # Execute the artifact lineage workflow in explicit, reviewable steps.
        queries = _required_service(use_cases.query_artifacts)
        return ArtifactLineageResponse.from_domain(queries.lineage(_artifact_id(artifact_id)))

    @app.get("/api/v1/runs", response_model=RunListResponse)
    def list_runs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
        # Offset is retained only as a bounded compatibility path.
        offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
        cursor: Annotated[
            str | None,
            Query(min_length=1, max_length=512, pattern=PAGE_TOKEN_PATTERN),
        ] = None,
    ) -> RunListResponse:
        # Execute the list runs workflow in explicit, reviewable steps.
        _require_exact_query_parameters(
            request,
            allowed=frozenset({"cursor", "limit", "offset"}),
        )
        queries = _required_service(use_cases.query_runs)
        page = queries.page(
            limit=limit,
            offset=offset,
            after=_run_list_cursor(cursor, logical_run_id=None, offset=offset),
        )
        return RunListResponse(
            items=tuple(RunSummaryResponse.from_domain(item) for item in page.items),
            next_cursor=(None if page.next_cursor is None else encode_run_cursor(page.next_cursor)),
        )

    @app.get("/api/v1/runs/{logical_run_id}", response_model=RunListResponse)
    def get_logical_run(
        logical_run_id: str,
        request: Request,
        # Keep the limit input explicit in the get logical run contract.
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
        offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
        cursor: Annotated[
            str | None,
            Query(min_length=1, max_length=512, pattern=PAGE_TOKEN_PATTERN),
        ] = None,
    ) -> RunListResponse:
        # Execute the get logical run workflow in explicit, reviewable steps.
        _require_exact_query_parameters(
            request,
            allowed=frozenset({"cursor", "limit", "offset"}),
        )
        queries = _required_service(use_cases.query_runs)
        resolved_logical_id = _logical_run_id(logical_run_id)
        page = queries.logical_page(
            resolved_logical_id,
            limit=limit,
            offset=offset,
            after=_run_list_cursor(
                cursor,
                logical_run_id=resolved_logical_id,
                offset=offset,
            ),
        )
        if not page.items:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RunListResponse(
            items=tuple(RunSummaryResponse.from_domain(item) for item in page.items),
            next_cursor=(None if page.next_cursor is None else encode_run_cursor(page.next_cursor)),
        )

    @app.get(
        # Pass api v1 run-artifacts artifact id explicitly so get receives a reviewable
        # /api/v1/run-artifacts/{artifact id}/summary and pumpfun sniping run summary
        # response input in pumpfun sniping run summary.
        "/api/v1/run-artifacts/{artifact_id}/summary",
        response_model=PumpfunSnipingRunSummaryResponse,
    )
    def pumpfun_sniping_run_summary(
        artifact_id: str,
        # Keep the pumpfun sniping run summary response input explicit in the pumpfun sniping
        # run summary contract.
    ) -> PumpfunSnipingRunSummaryResponse:
        # Execute the pumpfun sniping run summary workflow in explicit, reviewable steps.
        queries = _required_service(use_cases.query_run_results)
        response = PumpfunSnipingRunSummaryResponse.from_domain(
            queries.summary(_artifact_id(artifact_id))
        )
        return _bounded_api_response(response, max_request_bytes)

    @app.get(
        "/api/v1/run-artifacts/{artifact_id}/dashboard",
        response_model=PumpfunSnipingDashboardResponse,
    )
    def pumpfun_sniping_dashboard(
        request: Request,
        artifact_id: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 25,
    ) -> PumpfunSnipingDashboardResponse:
        # The combined route owns only the first-page limit; cursors use /roundtrips.
        _require_exact_query_parameters(request, allowed=frozenset({"limit"}))
        queries = _required_service(use_cases.query_run_results)
        response = PumpfunSnipingDashboardResponse.from_domain(
            queries.dashboard(
                _artifact_id(artifact_id),
                limit=limit,
            )
        )
        return _bounded_api_response(response, max_request_bytes)

    # Apply get semantics to the following pumpfun sniping roundtrips contract.
    @app.get(
        "/api/v1/run-artifacts/{artifact_id}/roundtrips",
        response_model=RoundTripPageResponse,
    )
    def pumpfun_sniping_roundtrips(
        request: Request,
        # Keep the artifact id input explicit in the pumpfun sniping roundtrips contract.
        artifact_id: str,
        after_target_boundary_ordinal: Annotated[
            str | None,
            Query(min_length=1, max_length=20, pattern=r"^(?:0|[1-9][0-9]*)$"),
        ] = None,
        # Keep the after roundtrip id input explicit in the pumpfun sniping roundtrips
        # contract.
        after_roundtrip_id: Annotated[
            str | None,
            Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 200,
        # Keep the round trip page response input explicit in the pumpfun sniping roundtrips
        # contract.
    ) -> RoundTripPageResponse:
        # Execute the pumpfun sniping roundtrips workflow in explicit, reviewable steps.
        _require_exact_query_parameters(
            request,
            allowed=frozenset({"after_roundtrip_id", "after_target_boundary_ordinal", "limit"}),
        )
        queries = _required_service(use_cases.query_run_results)
        cursor = _roundtrip_cursor(after_target_boundary_ordinal, after_roundtrip_id)
        response = RoundTripPageResponse.from_domain(
            queries.roundtrips(
                _artifact_id(artifact_id),
                # Pass after explicitly so roundtrips receives a reviewable artifact id
                # and cursor input in pumpfun sniping roundtrips.
                after=cursor,
                limit=limit,
            )
        )
        return _bounded_api_response(response, max_request_bytes)

    # Apply get semantics to the following system resources contract.
    @app.get("/api/v1/system/resources", response_model=SystemResourcesResponse)
    def system_resources() -> SystemResourcesResponse:
        # Execute the system resources workflow in explicit, reviewable steps.
        probe = _required_service(use_cases.system_resources)
        return SystemResourcesResponse.from_domain(probe.snapshot())

    @app.get("/api/v1/ml/reference-contract", response_model=ReferenceMlContractResponse)
    def ml_reference_contract() -> ReferenceMlContractResponse:
        # Execute the ml reference contract workflow in explicit, reviewable steps.
        contract = _required_service(use_cases.ml_reference_contract)
        return ReferenceMlContractResponse.from_domain(contract)

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(job_id: str) -> JobResponse:
        # Execute the cancel job workflow in explicit, reviewable steps.
        record = use_cases.cancel_job.execute(CancelJobRequest(_job_id(job_id)))
        _AUDIT_LOG.info("job_cancel_requested job_id=%s", record.job_id.value)
        return JobResponse.from_domain(record)

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_job(job_id: str) -> JobResponse:
        # Execute the retry job workflow in explicit, reviewable steps.
        retry = _required_service(use_cases.retry_job)
        record = retry.execute(RetryJobRequest(_job_id(job_id)))
        _AUDIT_LOG.info("job_retry_requested job_id=%s", record.job_id.value)
        return JobResponse.from_domain(record)

    return app


# Define bounded json body as one focused operation with an explicit boundary.
async def _bounded_json_body(request: Request, maximum: int) -> bytes:
    # Execute the bounded json body workflow in explicit, reviewable steps.
    media_type = request.headers.get("content-type", "").partition(";")[0].strip().casefold()
    if media_type != "application/json":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    content_encoding = request.headers.get("content-encoding", "identity").strip().casefold()
    if content_encoding not in {"", "identity"}:
        # Fail the bounded json body path with HTTPException for http 415 unsupported
        # media type and status when content encoding and identity is true; do not
        # continue ambiguously.
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
    content_lengths = request.headers.getlist("content-length")
    if len(content_lengths) > 1:
        raise InvalidJobPayloadError
    if content_lengths:
        # Handle the bounded json body content_lengths branch as a distinct logical block.
        raw_length = content_lengths[0]
        if not raw_length or any(character not in "0123456789" for character in raw_length):
            raise InvalidJobPayloadError
        if int(raw_length) > maximum:
            raise InvalidJobPayloadError

    # Assemble body once so the bounded json body workflow shares one value.
    body = bytearray()
    async for chunk in request.stream():
        # Process request.stream() inside the bounded bounded json body loop.
        if len(body) + len(chunk) > maximum:
            raise InvalidJobPayloadError
        body.extend(chunk)
    if not body:
        raise InvalidJobPayloadError
    # Return the completed bounded json body result without a hidden fallback.
    return bytes(body)


def _parse_job_command(raw: bytes) -> JobCommand:
    # Execute the parse job command workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse job command operation before explicit failure
        # handling.
        canonical = canonicalize_job_payload(raw)
        return JobCommand.model_validate_json(canonical)
    except (TypeError, ValueError):
        raise InvalidJobPayloadError from None


def _bounded_api_response[ResponseModelT: BaseModel](
    # Keep the value input explicit in the bounded api response contract.
    value: ResponseModelT,
    maximum: int,
) -> ResponseModelT:
    # Execute the bounded api response workflow in explicit, reviewable steps.
    if len(value.model_dump_json(by_alias=True).encode("utf-8")) > maximum:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
    return value


def _parse_plan_command(raw: bytes) -> PlanDatasetCommand:
    # Execute the parse plan command workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse plan command operation before explicit failure
        # handling.
        canonical = canonicalize_job_payload(raw)
        return PlanDatasetCommand.model_validate_json(canonical)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _parse_run_draft(raw: bytes) -> RunDraftCommand:
    # Execute the parse run draft workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse run draft operation before explicit failure
        # handling.
        canonical = canonicalize_job_payload(raw)
        return run_draft_command_from_bytes(canonical)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _parse_sweep_draft(raw: bytes) -> ReferenceSweepDraftCommand:
    # Execute the parse sweep draft workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse sweep draft operation before explicit failure
        # handling.
        canonical = canonicalize_job_payload(raw)
        return ReferenceSweepDraftCommand.model_validate_json(canonical)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _parse_run_backtest_command(raw: bytes) -> RunBacktestCommand:
    # Execute the parse run backtest command workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse run backtest command operation before explicit
        # failure handling.
        canonical = canonicalize_job_payload(raw)
        return RunBacktestCommand.model_validate_json(canonical)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _parse_ml_form[T: MlApiModel](raw: bytes, model: type[T]) -> T:
    # Execute the parse ml form workflow in explicit, reviewable steps.
    try:
        # Perform the protected parse ml form operation before explicit failure handling.
        canonical = canonicalize_job_payload(raw)
        return model.model_validate_json(canonical)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _submit_ml_job(
    # Keep the submitter input explicit in the submit ml job contract.
    submitter: SubmitJob,
    request: Request,
    response: Response,
    job_type: JobType,
    command: MlResolvedJob,
    # Keep the job response input explicit in the submit ml job contract.
) -> JobResponse:
    # Execute the submit ml job workflow in explicit, reviewable steps.
    idempotency_keys = request.headers.getlist("idempotency-key")
    if len(idempotency_keys) != 1:
        raise InvalidIdempotencyKeyError
    record = submitter.execute(
        SubmitJobRequest(
            # Pass spec version explicitly so SubmitJobRequest receives a reviewable
            # canonical bytes and input artifact ids input in submit ml job.
            spec_version=1,
            job_type=job_type,
            payload_json=command.canonical_bytes(),
            idempotency_key=idempotency_keys[0],
            input_artifact_ids=command.input_artifact_ids,
            # Complete SubmitJobRequest only after its canonical bytes and input artifact ids
            # inputs are visible in submit ml job.
        )
    )
    response.headers["Location"] = f"/api/v1/jobs/{record.job_id.value}"
    _AUDIT_LOG.info("job_created job_id=%s job_type=%s", record.job_id.value, record.spec.job_type)
    return JobResponse.from_domain(record)


# Define submit backtest job as one focused operation with an explicit boundary.
def _submit_backtest_job(
    submitter: SubmitJob,
    request: Request,
    response: Response,
    command: ResolvedBacktestJob,
    # Keep the job response input explicit in the submit backtest job contract.
) -> JobResponse:
    # Execute the submit backtest job workflow in explicit, reviewable steps.
    idempotency_keys = request.headers.getlist("idempotency-key")
    if len(idempotency_keys) != 1:
        raise InvalidIdempotencyKeyError
    record = submitter.execute(
        SubmitJobRequest(
            # Pass spec version explicitly so SubmitJobRequest receives a reviewable run
            # backtest and canonical bytes input in submit backtest job.
            spec_version=1,
            job_type=JobType.RUN_BACKTEST,
            payload_json=command.canonical_bytes(),
            idempotency_key=idempotency_keys[0],
        )
        # Complete execute only after its run backtest and canonical bytes inputs are visible
        # in submit backtest job.
    )
    response.headers["Location"] = f"/api/v1/jobs/{record.job_id.value}"
    _AUDIT_LOG.info("job_created job_id=%s job_type=%s", record.job_id.value, record.spec.job_type)
    return JobResponse.from_domain(record)


def _source_id(raw: str) -> SourceId:
    # Execute the source id workflow in explicit, reviewable steps.
    try:
        return SourceId(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _artifact_id(raw: str) -> ArtifactId:
    # Execute the artifact id workflow in explicit, reviewable steps.
    try:
        return ArtifactId(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _roundtrip_cursor(
    # Keep the target boundary ordinal input explicit in the roundtrip cursor contract.
    target_boundary_ordinal: str | None,
    roundtrip_id: str | None,
) -> RoundTripCursor | None:
    # Execute the roundtrip cursor workflow in explicit, reviewable steps.
    if target_boundary_ordinal is None and roundtrip_id is None:
        return None
    if target_boundary_ordinal is None or roundtrip_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    try:
        # Perform the protected roundtrip cursor operation before explicit failure
        # handling.
        return RoundTripCursor(
            target_boundary_ordinal=int(target_boundary_ordinal),
            roundtrip_id=ContentDigest(roundtrip_id),
        )
    except (TypeError, ValueError) as error:
        # Fail the roundtrip cursor path with HTTPException for http 422 unprocessable
        # content and status; do not continue ambiguously.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _job_list_cursor(
    value: str | None,
    *,
    state: AttemptState | None,
    offset: int,
) -> JobListCursor | None:
    """Decode one job token and reject ambiguous offset combinations."""

    if value is None:
        return None
    if offset != 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    try:
        return decode_job_cursor(value, state=state)
    except PageTokenError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _run_list_cursor(
    value: str | None,
    *,
    logical_run_id: LogicalRunId | None,
    offset: int,
) -> RunListCursor | None:
    """Decode one Run token and bind it to global/logical query scope."""

    if value is None:
        return None
    if offset != 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    try:
        return decode_run_cursor(value, logical_run_id=logical_run_id)
    except PageTokenError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _require_exact_query_parameters(request: Request, *, allowed: frozenset[str]) -> None:
    """Reject unknown or repeated query fields at a strict transport boundary."""

    keys = tuple(request.query_params.keys())
    # Repeated values are ambiguous even when the parameter name is allowlisted.
    has_duplicates = any(len(request.query_params.getlist(key)) != 1 for key in keys)
    if has_duplicates or any(key not in allowed for key in keys):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _logical_run_id(raw: str) -> LogicalRunId:
    # Execute the logical run id workflow in explicit, reviewable steps.
    try:
        return LogicalRunId(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _required_service[T](value: T | None) -> T:
    # Execute the required service workflow in explicit, reviewable steps.
    if value is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return value


def _job_id(raw: str) -> JobId:
    # Execute the job id workflow in explicit, reviewable steps.
    try:
        return JobId(raw)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from error


def _normalize_host(value: str) -> str:
    # Execute the normalize host workflow in explicit, reviewable steps.
    normalized = value.casefold().rstrip(".")
    if not normalized or any(ord(character) < 33 for character in normalized):
        raise ValueError("host allowlist contains an invalid name")
    return normalized


def _same_origin_request(request: Request) -> bool:
    # Execute the same origin request workflow in explicit, reviewable steps.
    if request.headers.get("sec-fetch-site", "").casefold() == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    # Keep expected failures inside the same origin request error boundary.
    try:
        # Perform the protected same origin request operation before explicit failure
        # handling.
        parsed = urlsplit(origin)
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        origin_host = _normalize_host(parsed.hostname or "")
        request_host = _normalize_host(request.url.hostname or "")
    # Translate value error through the same origin request boundary without hiding other
    # errors.
    except ValueError:
        return False
    return (
        parsed.scheme == request.url.scheme
        and parsed.username is None
        # Include parsed in the completed same origin request result.
        and parsed.password is None
        and origin_host == request_host
        and origin_port == request_port
        and parsed.path in {"", "/"}
        and not parsed.query
        # Include parsed in the completed same origin request result.
        and not parsed.fragment
    )


def _valid_mutation_session(request: Request, expected_token: str) -> bool:
    # Execute the valid mutation session workflow in explicit, reviewable steps.
    supplied = request.cookies.get(_SESSION_COOKIE)
    csrf = request.headers.get("x-backtest-csrf")
    return supplied is not None and hmac.compare_digest(supplied, expected_token) and csrf == "1"


# Keep the local write rate limiter contract and validation rules together.
class _LocalWriteRateLimiter:
    def __init__(self, maximum_per_minute: int) -> None:
        # Execute the local write rate limiter init workflow in explicit, reviewable
        # steps.
        self._maximum = maximum_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, peer: str) -> bool:
        # Execute the local write rate limiter allow workflow in explicit, reviewable
        # steps.
        now = time.monotonic()
        history = self._requests[peer]
        cutoff = now - 60
        while history and history[0] <= cutoff:
            history.popleft()
        # Guard this path with len(history) >= self._maximum before applying effects.
        if len(history) >= self._maximum:
            return False
        history.append(now)
        if len(self._requests) > 64:
            # Handle the local write rate limiter allow len(self._requests) > 64 branch as
            # a distinct logical block.
            for key in tuple(self._requests):
                # Process tuple(self._requests) inside the bounded local write rate
                # limiter allow loop.
                if not self._requests[key]:
                    del self._requests[key]
        return True


def _web_page_response(
    path: Path,
    *,
    enforce_session: bool,
    session_token: str,
    secure_cookie: bool,
) -> FileResponse:
    """Return one packaged UI page with the local session bootstrap cookie."""

    response = FileResponse(path)
    if enforce_session:
        response.set_cookie(
            _SESSION_COOKIE,
            session_token,
            httponly=True,
            secure=secure_cookie,
            samesite="strict",
            path="/",
        )
    return response


def _secured_response(response: Response, *, api: bool) -> Response:
    # Execute the secured response workflow in explicit, reviewable steps.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        # Keep the default-src component named inside the headers, content-security-policy
        # and response contract.
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers["Cache-Control"] = "no-store" if api else "no-cache"
    # Return the completed secured response result without a hidden fallback.
    return response


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    # Execute the error response workflow in explicit, reviewable steps.
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(code=code, message=message).model_dump(),
    )


def _http_error_code(status_code: int) -> str:
    # Execute the http error code workflow in explicit, reviewable steps.
    return {
        status.HTTP_413_CONTENT_TOO_LARGE: "RESPONSE_TOO_LARGE",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_MEDIA_TYPE",
        # Pass status explicitly so get receives a reviewable http error and status code
        # input in http error code.
        status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
    }.get(status_code, "HTTP_ERROR")


def _http_error_message(status_code: int) -> str:
    # Execute the http error message workflow in explicit, reviewable steps.
    return {
        status.HTTP_413_CONTENT_TOO_LARGE: (
            "The resolved response exceeds the configured local transport bound."
        ),
        status.HTTP_404_NOT_FOUND: "The requested local API resource does not exist.",
        # Pass status explicitly so get receives a reviewable value and status code input
        # in http error message.
        status.HTTP_405_METHOD_NOT_ALLOWED: "The HTTP method is not supported for this resource.",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Request body must use unencoded application/json.",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "Request does not match the versioned API schema.",
    }.get(status_code, "The HTTP request could not be completed.")


def _package_version() -> str:
    # Execute the package version workflow in explicit, reviewable steps.
    try:
        return version("on-chain-backtest-engine")
    except PackageNotFoundError:
        return "0+unknown"


__all__ = ["ControlUseCases", "create_app"]
