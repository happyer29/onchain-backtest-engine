"""Strict stdlib HTTP client for one configured loopback Control API."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable

# Import dataclasses at the visible module dependency boundary.
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from hashlib import sha256
from http.cookies import CookieError, SimpleCookie
from ipaddress import ip_address

# Import typing at the visible module dependency boundary.
from typing import Final, Never
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import (
    HTTPRedirectHandler,
    # Include opener director so the request dependency remains explicit.
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

# Import canonical json at the visible module dependency boundary.
from backtest.application.canonical_json import canonicalize_job_payload
from backtest.application.job_views import JobStatusView
from backtest.application.models import (
    ArtifactKind,
    AttemptState,
    # Include committed artifact so the models dependency remains explicit.
    CommittedArtifact,
    JobEventRecord,
    JobProgressDetails,
    JobType,
    ListJobsRequest,
    # Include progress level so the models dependency remains explicit.
    ProgressLevel,
    ProgressStage,
)
from backtest.application.ports.run_results import (
    MAX_ROUNDTRIP_PAGE_SIZE,
    # Include round trip cursor so the run results dependency remains explicit.
    RoundTripCursor,
    RoundTripPage,
)
from backtest.application.run_contracts import (
    RunContractDescriptor,
    # Include run contract field so the run contracts dependency remains explicit.
    RunContractField,
    RunFieldKind,
)
from backtest.application.run_results import (
    MAX_RUN_WARNINGS,
    # Include run backend so the run results dependency remains explicit.
    RunBackend,
    RunComparisonProjection,
    RunPhysicalSettings,
    validate_run_warnings,
)

# Import run specs at the visible module dependency boundary.
from backtest.application.run_specs import ReplayContract
from backtest.application.use_cases.query_artifacts import (
    MAX_ARTIFACT_LINEAGE_ITEMS,
    ArtifactDetails,
    ArtifactLineage,
    # Include lineage edge so the query artifacts dependency remains explicit.
    LineageEdge,
)
from backtest.application.use_cases.query_run_results import PumpfunSnipingRunSummaryView
from backtest.application.use_cases.query_runs import RunSummaryView
from backtest.application.use_cases.submit_job import SubmitJobRequest
from backtest.domain.execution import ExecutionMode

# Import hashing at the visible module dependency boundary.
from backtest.domain.hashing import canonical_json_bytes
from backtest.domain.identifiers import (
    ArtifactId,
    AttemptId,
    ContentDigest,
    # Include execution attempt id so the identifiers dependency remains explicit.
    ExecutionAttemptId,
    JobId,
    LogicalRunId,
    NetworkId,
    PositionSchemaId,
    # Close the identifiers import after its required symbols are visible.
)
from backtest.domain.roundtrips import (
    ROUNDTRIP_RESULT_SCHEMA_V3,
    ROUNDTRIP_RESULT_SCHEMA_V4,
    RoundTripRecord,
    roundtrip_record_from_document,
)
from backtest.engine.sniping import SnipingValuationStatus

_SESSION_COOKIE: Final = "backtest_session"
_MAXIMUM_SAFE_ERROR_MESSAGE: Final = 512
# Bind error code once as an explicit module-level contract.
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,512}")
# Delegated callers treat list continuations as opaque bounded transport values.
_PAGE_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")


@dataclass(frozen=True, slots=True)
class ControlHealth:
    """Strict identity-bearing health document for one local controller."""

    profile: str
    version: str
    control_plane_id: ContentDigest


class ControlApiUnavailableError(RuntimeError):
    """The configured local controller cannot be reached within the bound."""

    def __init__(self) -> None:
        super().__init__("The configured loopback Control API is unavailable.")


class ControlApiProtocolError(RuntimeError):
    """The peer did not implement the strict bounded local API contract."""

    def __init__(self) -> None:
        super().__init__("The loopback Control API returned an invalid response.")


class ControlApiError(RuntimeError):
    """A stable safe error explicitly returned by the local Control API."""

    def __init__(self, status_code: int, code: str, safe_message: str) -> None:
        # Execute the control api error init workflow in explicit, reviewable steps.
        self.status_code = status_code
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


# Keep the no redirects contract and validation rules together.
class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: object,
        # Keep the code input explicit in the redirect request contract.
        code: int,
        msg: str,
        headers: Message[str, str],
        newurl: str,
    ) -> Never:
        # Execute the no redirects redirect request workflow in explicit, reviewable
        # steps.
        del req, fp, code, msg, headers, newurl
        raise ControlApiProtocolError


class LocalControlApiClient:
    """A finite, proxy-free client that can only address an explicit loopback peer."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        # Keep the timeout seconds input explicit in the init contract.
        timeout_seconds: float = 2.0,
        maximum_response_bytes: int = 2 * 1024 * 1024,
        opener: OpenerDirector | None = None,
    ) -> None:
        # Execute the local control api client init workflow in explicit, reviewable
        # steps.
        normalized_host = _loopback_host(host)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            raise ValueError("Control API port must be between 1 and 65535")
        if (
            isinstance(timeout_seconds, bool)
            # Keep isinstance visible while evaluating the isinstance, timeout seconds and
            # isfinite guard.
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("Control API timeout must be finite and between 0 and 30 seconds")
        # Evaluate the complete local control api client init isinstance and maximum
        # response bytes condition before guarded effects.
        if (
            isinstance(maximum_response_bytes, bool)
            or not isinstance(maximum_response_bytes, int)
            or not 1 <= maximum_response_bytes <= 8 * 1024 * 1024
        ):
            # Fail the local control api client init path with ValueError for control api
            # response bound must be between 1 byte and 8 mi b when isinstance and maximum
            # response bytes is true; do not continue ambiguously.
            raise ValueError("Control API response bound must be between 1 byte and 8 MiB")
        authority = f"[{normalized_host}]" if ":" in normalized_host else normalized_host
        self._origin = f"http://{authority}:{port}"
        self._timeout_seconds = float(timeout_seconds)
        self._maximum_response_bytes = maximum_response_bytes
        # Assemble self opener once so the local control api client init workflow shares
        # one value.
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirects())
        self._session_token: str | None = None

    @property
    def origin(self) -> str:
        return self._origin

    # Define local control api client health as one focused operation with an explicit
    # boundary.
    def health(self) -> ControlHealth:
        # Execute the local control api client health workflow in explicit, reviewable
        # steps.
        document = self._request_json("GET", "/api/v1/health")
        if set(document) != {"control_plane_id", "profile", "status", "version"}:
            raise ControlApiProtocolError
        if document["status"] != "ok":
            raise ControlApiProtocolError
        # Traverse ('profile', 'version') explicitly so each local control api client
        # health iteration remains traceable.
        for field in ("profile", "version"):
            # Process ('profile', 'version') inside the bounded local control api client
            # health loop.
            if not _safe_text(document[field], maximum=256):
                raise ControlApiProtocolError
        try:
            control_plane_id = ContentDigest(_string_field(document, "control_plane_id"))
        except ValueError:
            # Fail the local control api client health path with ControlApiProtocolError;
            # do not continue ambiguously.
            raise ControlApiProtocolError from None
        return ControlHealth(
            profile=_string_field(document, "profile"),
            version=_string_field(document, "version"),
            control_plane_id=control_plane_id,
            # Complete ControlHealth only after its profile and version inputs are visible in
            # local control api client health.
        )

    def run_physical_settings(self) -> RunPhysicalSettings:
        return _run_physical_settings(self._request_json("GET", "/api/v1/run-physical-settings"))

    def run_contract(self, schema: str) -> RunContractDescriptor:
        """Return one exact advertised run-draft contract from the bounded list."""

        response = self._request_json("GET", "/api/v1/run-contracts")
        if set(response) != {"items"} or not isinstance(response["items"], list):
            raise ControlApiProtocolError
        if len(response["items"]) > 32:
            raise ControlApiProtocolError
        # Assemble contracts once so the local control api client run contract workflow
        # shares one value.
        contracts = tuple(_run_contract(item) for item in response["items"])
        schemas = tuple(item.schema for item in contracts)
        if schemas != tuple(sorted(set(schemas))):
            raise ControlApiProtocolError
        selected = tuple(item for item in contracts if item.schema == schema)
        # Guard this path with len(selected) != 1 before applying effects.
        if len(selected) != 1:
            raise ControlApiError(404, "RUN_CONTRACT_NOT_FOUND", "Run contract was not found.")
        return selected[0]

    def sniping_run_summary(self, artifact_id: ArtifactId) -> PumpfunSnipingRunSummaryView:
        # Execute the local control api client sniping run summary workflow in explicit,
        # reviewable steps.
        path = f"/api/v1/run-artifacts/{quote(artifact_id.hex, safe='')}/summary"
        result = _sniping_run_summary(self._request_json("GET", path))
        if result.run_artifact_id != artifact_id:
            raise ControlApiProtocolError
        return result

    # Define local control api client sniping roundtrips as one focused operation with an
    # explicit boundary.
    def sniping_roundtrips(
        self,
        artifact_id: ArtifactId,
        *,
        after: RoundTripCursor | None,
        # Keep the limit input explicit in the sniping roundtrips contract.
        limit: int,
    ) -> RoundTripPage:
        # Execute the local control api client sniping roundtrips workflow in explicit,
        # reviewable steps.
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_ROUNDTRIP_PAGE_SIZE
        ):
            # Fail the local control api client sniping roundtrips path with ValueError
            # for round-trip page limit must be between 1 and 200 when isinstance, limit
            # and max roundtrip page size is true; do not continue ambiguously.
            raise ValueError("Round-trip page limit must be between 1 and 200")
        query: dict[str, str | int] = {"limit": limit}
        if after is not None:
            # Handle the local control api client sniping roundtrips after is not None
            # branch as a distinct logical block.
            query["after_target_boundary_ordinal"] = str(after.target_boundary_ordinal)
            query["after_roundtrip_id"] = after.roundtrip_id.hex
        path = (
            f"/api/v1/run-artifacts/{quote(artifact_id.hex, safe='')}/roundtrips?{urlencode(query)}"
        )
        # Return the completed local control api client sniping roundtrips result without
        # a hidden fallback.
        return _roundtrip_page(self._request_json("GET", path), after=after, limit=limit)

    def acquire_session(self) -> None:
        # Execute the local control api client acquire session workflow in explicit,
        # reviewable steps.
        _, headers, _ = self._request("GET", "/", expect_json=False)
        set_cookies = headers.get_all("Set-Cookie", failobj=[])
        if len(set_cookies) != 1:
            raise ControlApiProtocolError
        cookie = SimpleCookie()
        # Keep expected failures inside the local control api client acquire session error
        # boundary.
        try:
            # Perform the protected local control api client acquire session operation
            # before explicit failure handling.
            cookie.load(set_cookies[0])
            token = cookie[_SESSION_COOKIE].value
        except (CookieError, KeyError):
            raise ControlApiProtocolError from None
        if _SESSION_TOKEN.fullmatch(token) is None:
            # Fail the local control api client acquire session path with
            # ControlApiProtocolError when fullmatch, token and session token is true; do
            # not continue ambiguously.
            raise ControlApiProtocolError
        self._session_token = token

    def submit_job(self, request: SubmitJobRequest) -> JobStatusView:
        # Execute the local control api client submit job workflow in explicit, reviewable
        # steps.
        try:
            payload = _load_json_object(canonicalize_job_payload(request.payload_json))
        except (TypeError, ValueError):
            raise ControlApiProtocolError from None
        document = {
            # Keep the input artifact ids component named inside the document contract.
            "input_artifact_ids": [item.hex for item in request.input_artifact_ids],
            "job_type": request.job_type.value,
            "payload": payload,
            "spec_version": request.spec_version,
        }
        # Assemble response once so the local control api client submit job workflow
        # shares one value.
        response = self._request_json(
            "POST",
            "/api/v1/jobs",
            body=canonical_json_bytes(document),
            idempotency_key=request.idempotency_key,
            # Complete _request_json only after its post and /api/v1/jobs inputs are visible
            # in local control api client submit job.
        )
        return _job_status(response)

    def list_jobs(self, request: ListJobsRequest) -> tuple[JobStatusView, ...]:
        # Execute the local control api client list jobs workflow in explicit, reviewable
        # steps.
        query: dict[str, str | int] = {"limit": request.limit, "offset": request.offset}
        if request.state is not None:
            query["state"] = request.state.value
        response = self._request_json("GET", f"/api/v1/jobs?{urlencode(query)}")
        if set(response) != {"items", "next_cursor"} or not isinstance(
            response["items"],
            list,
        ):
            # Fail the local control api client list jobs path with
            # ControlApiProtocolError when response, items and isinstance is true; do not
            # continue ambiguously.
            raise ControlApiProtocolError
        _optional_page_cursor(response["next_cursor"])
        if len(response["items"]) > request.limit:
            raise ControlApiProtocolError
        return tuple(_job_status(item) for item in response["items"])

    def get_job(self, job_id: JobId) -> JobStatusView:
        # Return the completed local control api client get job result without a hidden
        # fallback.
        return _job_status(self._request_json("GET", _job_path(job_id)))

    def cancel_job(self, job_id: JobId) -> JobStatusView:
        return _job_status(self._request_json("POST", f"{_job_path(job_id)}/cancel", body=b"{}"))

    def retry_job(self, job_id: JobId) -> JobStatusView:
        return _job_status(self._request_json("POST", f"{_job_path(job_id)}/retry", body=b"{}"))

    # Define local control api client list job events as one focused operation with an
    # explicit boundary.
    def list_job_events(
        self,
        job_id: JobId,
        *,
        after_event_id: int = 0,
        # Keep the limit input explicit in the list job events contract.
        limit: int = 200,
    ) -> tuple[JobEventRecord, ...]:
        # Execute the local control api client list job events workflow in explicit,
        # reviewable steps.
        if (
            isinstance(after_event_id, bool)
            or not isinstance(after_event_id, int)
            or after_event_id < 0
            or isinstance(limit, bool)
            # Keep isinstance visible while evaluating the isinstance, after event id and
            # limit guard.
            or not isinstance(limit, int)
            or not 1 <= limit <= 1_000
        ):
            raise ValueError("Job event cursor and limit are outside the bounded contract")
        query = urlencode({"after_event_id": after_event_id, "limit": limit})
        # Assemble response once so the local control api client list job events workflow
        # shares one value.
        response = self._request_json("GET", f"{_job_path(job_id)}/events?{query}")
        if set(response) != {"items"} or not isinstance(response["items"], list):
            raise ControlApiProtocolError
        if len(response["items"]) > limit:
            raise ControlApiProtocolError
        # Assemble events once so the local control api client list job events workflow
        # shares one value.
        events = tuple(_job_event(item) for item in response["items"])
        if any(event.job_id != job_id for event in events):
            raise ControlApiProtocolError
        event_ids = tuple(event.event_id for event in events)
        if event_ids != tuple(sorted(set(event_ids))) or any(
            # Pass event id explicitly so any receives a reviewable event id and after
            # event id input in local control api client list job events.
            event_id <= after_event_id
            for event_id in event_ids
        ):
            raise ControlApiProtocolError
        return events

    # Define local control api client artifact document as one focused operation with an
    # explicit boundary.
    def artifact_document(self, artifact_id: ArtifactId) -> ArtifactDetails:
        # Execute the local control api client artifact document workflow in explicit,
        # reviewable steps.
        document = self._request_json(
            "GET",
            f"/api/v1/artifacts/{quote(artifact_id.hex, safe='')}",
        )
        if set(document) != {"descriptor", "manifest"}:
            # Fail the local control api client artifact document path with
            # ControlApiProtocolError when document, descriptor and manifest is true; do
            # not continue ambiguously.
            raise ControlApiProtocolError
        descriptor = _artifact_descriptor(document["descriptor"])
        if descriptor.artifact_id != artifact_id:
            raise ControlApiProtocolError
        manifest = _require_object(document["manifest"])
        # Keep expected failures inside the local control api client artifact document
        # error boundary.
        try:
            manifest_bytes = canonical_json_bytes(manifest)
        except (TypeError, ValueError):
            raise ControlApiProtocolError from None
        if sha256(manifest_bytes).hexdigest() != descriptor.manifest_digest.hex:
            # Fail the local control api client artifact document path with
            # ControlApiProtocolError when hex, hexdigest and manifest digest is true; do
            # not continue ambiguously.
            raise ControlApiProtocolError
        try:
            return ArtifactDetails(descriptor, manifest_bytes)
        except ValueError:
            raise ControlApiProtocolError from None

    # Define local control api client lineage document as one focused operation with an
    # explicit boundary.
    def lineage_document(self, artifact_id: ArtifactId) -> ArtifactLineage:
        # Execute the local control api client lineage document workflow in explicit,
        # reviewable steps.
        document = self._request_json(
            "GET",
            f"/api/v1/lineage/{quote(artifact_id.hex, safe='')}",
        )
        if set(document) != {"artifacts", "edges", "root_artifact_id"}:
            # Fail the local control api client lineage document path with
            # ControlApiProtocolError when document, artifacts and edges is true; do not
            # continue ambiguously.
            raise ControlApiProtocolError
        artifacts = document["artifacts"]
        edges = document["edges"]
        if (
            not isinstance(artifacts, list)
            # Keep isinstance visible while evaluating the max artifact lineage items,
            # isinstance and artifacts guard.
            or not isinstance(edges, list)
            or len(artifacts) > MAX_ARTIFACT_LINEAGE_ITEMS
            or len(edges) > MAX_ARTIFACT_LINEAGE_ITEMS
        ):
            raise ControlApiProtocolError
        # Keep expected failures inside the local control api client lineage document
        # error boundary.
        try:
            # Perform the protected local control api client lineage document operation
            # before explicit failure handling.
            root_artifact_id = ArtifactId(_string_field(document, "root_artifact_id"))
            result = ArtifactLineage(
                root_artifact_id=root_artifact_id,
                artifacts=tuple(_artifact_descriptor(item) for item in artifacts),
                edges=tuple(_lineage_edge(item) for item in edges),
                # Complete ArtifactLineage only after its tuple and artifact descriptor inputs
                # are visible in local control api client lineage document.
            )
        except (TypeError, ValueError):
            raise ControlApiProtocolError from None
        if result.root_artifact_id != artifact_id:
            raise ControlApiProtocolError
        # Return the completed local control api client lineage document result without a
        # hidden fallback.
        return result

    def run_documents(
        self,
        *,
        logical_run_id: str | None = None,
        # Keep the limit input explicit in the run documents contract.
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[RunSummaryView, ...]:
        # Execute the local control api client run documents workflow in explicit,
        # reviewable steps.
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 50
            or isinstance(offset, bool)
            # Keep isinstance visible while evaluating the isinstance, limit and offset
            # guard.
            or not isinstance(offset, int)
            or not 0 <= offset <= 10_000
        ):
            raise ValueError("Run query bounds are invalid")
        query = urlencode({"limit": limit, "offset": offset})
        # Guard this path with logical_run_id is None before applying effects.
        if logical_run_id is None:
            path = f"/api/v1/runs?{query}"
        else:
            # Handle the local control api client run documents complement of
            # logical_run_id is None explicitly.
            digest = ContentDigest(logical_run_id)
            path = f"/api/v1/runs/{quote(digest.hex, safe='')}?{query}"
        response = self._request_json("GET", path)
        if set(response) != {"items", "next_cursor"} or not isinstance(
            response["items"],
            list,
        ):
            raise ControlApiProtocolError
        _optional_page_cursor(response["next_cursor"])
        # Guard this path with len(response['items']) > limit before applying effects.
        if len(response["items"]) > limit:
            raise ControlApiProtocolError
        items = tuple(_run_summary(item) for item in response["items"])
        if logical_run_id is not None and any(
            item.logical_run_id.hex != logical_run_id
            # Pass item explicitly so any receives a reviewable hex and logical run id
            # input in local control api client run documents.
            for item in items
            # Complete any only after its hex and logical run id inputs are visible in local
            # control api client run documents.
        ):
            raise ControlApiProtocolError
        return items

    def _request_json(
        self,
        # Keep the method input explicit in the request json contract.
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        idempotency_key: str | None = None,
        # Keep the dict input explicit in the request json contract.
    ) -> dict[str, object]:
        # Execute the local control api client request json workflow in explicit,
        # reviewable steps.
        status_code, _, payload = self._request(
            method,
            path,
            body=body,
            idempotency_key=idempotency_key,
            # Pass expect json explicitly so _request receives a reviewable method and
            # path input in local control api client request json.
            expect_json=True,
        )
        if not 200 <= status_code < 300:
            raise ControlApiProtocolError
        try:
            # Return the completed local control api client request json result without a
            # hidden fallback.
            return _load_json_object(payload)
        except (TypeError, ValueError):
            raise ControlApiProtocolError from None

    def _request(
        self,
        # Keep the method input explicit in the request contract.
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        idempotency_key: str | None = None,
        # Keep the expect json input explicit in the request contract.
        expect_json: bool,
    ) -> tuple[int, Message[str, str], bytes]:
        # Execute the local control api client request workflow in explicit, reviewable
        # steps.
        if method not in {"GET", "POST"} or not path.startswith("/") or "\\" in path:
            raise ValueError("Control API request target is invalid")
        if any(ord(character) < 33 or ord(character) > 126 for character in path):
            raise ValueError("Control API request target contains unsafe characters")
        headers = {
            "Accept": "application/json",
            "User-Agent": "on-chain-backtest-engine-cli/1",
        }
        # Guard this path with body is not None before applying effects.
        if body is not None:
            # Handle the local control api client request body is not None branch as a
            # distinct logical block.
            if method != "POST":
                raise ValueError("Only Control API mutations may include a request body")
            if len(body) > self._maximum_response_bytes:
                raise ValueError("Control API request body exceeds the local bound")
            if self._session_token is None:
                # Invoke acquire_session as a visible step within the local control api
                # client request workflow.
                self.acquire_session()
            headers.update(
                {
                    "Content-Type": "application/json",
                    "Cookie": f"{_SESSION_COOKIE}={self._session_token}",
                    # Keep origin named so the content-type and cookie payload passed to
                    # update remains self-describing within local control api client
                    # request.
                    "Origin": self._origin,
                    "X-Backtest-CSRF": "1",
                }
            )
        if idempotency_key is not None:
            # Handle the local control api client request idempotency_key is not None
            # branch as a distinct logical block.
            if not _safe_text(idempotency_key, maximum=512):
                raise ValueError("Idempotency key is invalid")
            headers["Idempotency-Key"] = idempotency_key
        request = Request(f"{self._origin}{path}", data=body, headers=headers, method=method)
        try:
            # Perform the protected local control api client request operation before
            # explicit failure handling.
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                # Keep open, request and opener active only for the bounded local control
                # api client request operation.
                response_payload = _bounded_body(
                    response.headers,
                    response.read,
                    maximum=self._maximum_response_bytes,
                )
                # Assemble status code once so the local control api client request
                # workflow shares one value.
                status_code = response.status
                response_headers = response.headers
        except HTTPError as error:
            # Translate the HTTPError failure through the local control api client request
            # boundary.
            payload = _bounded_body(
                error.headers,
                error.read,
                maximum=self._maximum_response_bytes,
            )
            # Invoke _raise_api_error for code and headers as a visible local control api
            # client request step.
            self._raise_api_error(error.code, error.headers, payload)
        except ControlApiProtocolError:
            raise
        except (OSError, TimeoutError, URLError):
            raise ControlApiUnavailableError from None
        # Guard this path with not 200 <= status_code < 300 before applying effects.
        if not 200 <= status_code < 300:
            self._raise_api_error(status_code, response_headers, response_payload)
        if expect_json:
            _require_json_content_type(response_headers)
        return status_code, response_headers, response_payload

    # Apply staticmethod semantics to the following local control api client raise api
    # error contract.
    @staticmethod
    def _raise_api_error(status_code: int, headers: Message[str, str], payload: bytes) -> Never:
        # Execute the local control api client raise api error workflow in explicit,
        # reviewable steps.
        _require_json_content_type(headers)
        try:
            document = _load_json_object(payload)
        except (TypeError, ValueError):
            raise ControlApiProtocolError from None
        # Guard this path with set(document) != {'code', 'message'} before applying
        # effects.
        if set(document) != {"code", "message"}:
            raise ControlApiProtocolError
        code = _string_field(document, "code")
        message = _string_field(document, "message")
        if _ERROR_CODE.fullmatch(code) is None or not _safe_text(
            # Pass maximum explicitly so _safe_text receives a reviewable message and
            # maximum safe error message input in local control api client raise api
            # error.
            message,
            maximum=_MAXIMUM_SAFE_ERROR_MESSAGE,
        ):
            raise ControlApiProtocolError
        raise ControlApiError(status_code, code, message)


# Define loopback host as one focused operation with an explicit boundary.
def _loopback_host(value: str) -> str:
    # Execute the loopback host workflow in explicit, reviewable steps.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Control API host must be a non-empty loopback name")
    normalized = value.casefold().removesuffix(".")
    if normalized == "localhost":
        return normalized
    # Keep expected failures inside the loopback host error boundary.
    try:
        parsed = ip_address(normalized)
    except ValueError:
        raise ValueError("Control API client only accepts an explicit loopback host") from None
    if not parsed.is_loopback:
        # Fail the loopback host path with ValueError for control api client only accepts
        # an explicit loopback host when is loopback and parsed is true; do not continue
        # ambiguously.
        raise ValueError("Control API client only accepts an explicit loopback host")
    return parsed.compressed


def _job_path(job_id: JobId) -> str:
    return f"/api/v1/jobs/{quote(job_id.value, safe='')}"


def _bounded_body(
    # Keep the headers input explicit in the bounded body contract.
    headers: Message[str, str],
    read: Callable[[int], bytes],
    *,
    maximum: int,
) -> bytes:
    # Execute the bounded body workflow in explicit, reviewable steps.
    lengths = headers.get_all("Content-Length", failobj=[])
    if len(lengths) > 1:
        raise ControlApiProtocolError
    if lengths:
        # Handle the bounded body lengths branch as a distinct logical block.
        length = lengths[0]
        if not length.isascii() or not length.isdecimal() or int(length) > maximum:
            raise ControlApiProtocolError
    payload = read(maximum + 1)
    if (
        # Keep isinstance visible while evaluating the maximum, lengths and isinstance
        # guard.
        not isinstance(payload, bytes)
        or len(payload) > maximum
        or (lengths and len(payload) != int(lengths[0]))
    ):
        raise ControlApiProtocolError
    # Return the completed bounded body result without a hidden fallback.
    return payload


def _require_json_content_type(headers: Message[str, str]) -> None:
    # Execute the require json content type workflow in explicit, reviewable steps.
    values = headers.get_all("Content-Type", failobj=[])
    if len(values) != 1 or values[0].partition(";")[0].strip().casefold() != "application/json":
        raise ControlApiProtocolError


def _load_json_object(payload: bytes) -> dict[str, object]:
    # Execute the load json object workflow in explicit, reviewable steps.
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        # Execute the no duplicates workflow in explicit, reviewable steps.
        document: dict[str, object] = {}
        for key, value in pairs:
            # Process pairs inside the bounded no duplicates loop.
            if key in document:
                raise ValueError("duplicate JSON key")
            document[key] = value
        return document

    value = json.loads(payload, object_pairs_hook=no_duplicates)
    # Return the completed load json object result without a hidden fallback.
    return _require_object(value)


def _require_object(value: object) -> dict[str, object]:
    # Execute the require object workflow in explicit, reviewable steps.
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("JSON root must be an object")
    return value


def _job_status(value: object) -> JobStatusView:
    # Execute the job status workflow in explicit, reviewable steps.
    document = _require_object(value)
    expected = {
        "input_artifact_count",
        "input_artifact_ids_digest",
        "job_id",
        # Keep the job type component named inside the expected contract.
        "job_type",
        "payload_digest",
        "spec_id",
        "spec_version",
        "state",
        # Keep the state version component named inside the expected contract.
        "state_version",
        "submitted_at_ns",
        "updated_at_ns",
    }
    if set(document) != expected:
        raise ControlApiProtocolError
    try:
        # Perform the protected job status operation before explicit failure handling.
        return JobStatusView(
            job_id=JobId(_string_field(document, "job_id")),
            spec_version=_integer_field(document, "spec_version", minimum=1),
            spec_id=ContentDigest(_string_field(document, "spec_id")),
            job_type=JobType(_string_field(document, "job_type")),
            # Include payload digest in the completed job status result.
            payload_digest=ContentDigest(_string_field(document, "payload_digest")),
            input_artifact_count=_integer_field(
                document,
                "input_artifact_count",
                minimum=0,
                # Complete _integer_field only after its input artifact count and document
                # inputs are visible in job status.
            ),
            input_artifact_ids_digest=ContentDigest(
                _string_field(document, "input_artifact_ids_digest")
            ),
            state=AttemptState(_string_field(document, "state")),
            # Include state version in the completed job status result.
            state_version=_integer_field(document, "state_version", minimum=0),
            submitted_at_ns=_decimal_integer_field(document, "submitted_at_ns", signed=False),
            updated_at_ns=_decimal_integer_field(document, "updated_at_ns", signed=False),
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


def _artifact_descriptor(value: object) -> CommittedArtifact:
    # Execute the artifact descriptor workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "artifact_id",
        "build_key",
        "input_artifact_ids",
        # Keep kind visible while evaluating the document, artifact id and build key
        # guard.
        "kind",
        "manifest_digest",
    }:
        raise ControlApiProtocolError
    inputs = document["input_artifact_ids"]
    # Evaluate the complete artifact descriptor max artifact lineage items, isinstance and
    # inputs condition before guarded effects.
    if (
        not isinstance(inputs, list)
        or len(inputs) > MAX_ARTIFACT_LINEAGE_ITEMS
        or not all(isinstance(item, str) for item in inputs)
    ):
        # Fail the artifact descriptor path with ControlApiProtocolError when max artifact
        # lineage items, isinstance and inputs is true; do not continue ambiguously.
        raise ControlApiProtocolError
    try:
        # Perform the protected artifact descriptor operation before explicit failure
        # handling.
        input_artifact_ids = tuple(ArtifactId(item) for item in inputs)
        if input_artifact_ids != tuple(sorted(set(input_artifact_ids), key=lambda item: item.hex)):
            raise ValueError("artifact inputs are not canonical")
        return CommittedArtifact(
            artifact_id=ArtifactId(_string_field(document, "artifact_id")),
            # Include kind in the completed artifact descriptor result.
            kind=ArtifactKind(_string_field(document, "kind")),
            manifest_digest=ContentDigest(_string_field(document, "manifest_digest")),
            build_key=ContentDigest(_string_field(document, "build_key")),
            input_artifact_ids=input_artifact_ids,
        )
    # Translate type error through the artifact descriptor boundary without hiding other
    # errors.
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


def _lineage_edge(value: object) -> LineageEdge:
    # Execute the lineage edge workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {"input_artifact_id", "output_artifact_id"}:
        raise ControlApiProtocolError
    try:
        # Perform the protected lineage edge operation before explicit failure handling.
        return LineageEdge(
            output_artifact_id=ArtifactId(_string_field(document, "output_artifact_id")),
            input_artifact_id=ArtifactId(_string_field(document, "input_artifact_id")),
        )
    except (TypeError, ValueError):
        # Fail the lineage edge path with ControlApiProtocolError; do not continue
        # ambiguously.
        raise ControlApiProtocolError from None


def _run_contract(value: object) -> RunContractDescriptor:
    # Execute the run contract workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {"editable_fields", "fixed_semantics", "schema", "title"}:
        raise ControlApiProtocolError
    editable = document["editable_fields"]
    fixed = document["fixed_semantics"]
    # Evaluate the complete run contract isinstance, editable and fixed condition before
    # guarded effects.
    if (
        not isinstance(editable, list)
        or len(editable) > 64
        or not isinstance(fixed, dict)
        or len(fixed) > 64
        # Keep all visible while evaluating the isinstance, editable and fixed guard.
        or not all(isinstance(key, str) and isinstance(item, str) for key, item in fixed.items())
    ):
        raise ControlApiProtocolError
    try:
        # Perform the protected run contract operation before explicit failure handling.
        result = RunContractDescriptor(
            schema=_string_field(document, "schema"),
            title=_string_field(document, "title"),
            editable_fields=tuple(_run_contract_field(item) for item in editable),
            fixed_semantics=tuple(sorted(fixed.items())),
            # Complete RunContractDescriptor only after its schema and title inputs are
            # visible in run contract.
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None
    return result


def _run_contract_field(value: object) -> RunContractField:
    # Execute the run contract field workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {"enum_values", "kind", "name", "required"}:
        raise ControlApiProtocolError
    enum_values = document["enum_values"]
    required = document["required"]
    # Evaluate the complete run contract field isinstance, enum values and required
    # condition before guarded effects.
    if (
        not isinstance(enum_values, list)
        or len(enum_values) > 64
        or not all(isinstance(item, str) for item in enum_values)
        or not isinstance(required, bool)
        # Evaluate the complete run contract field isinstance, enum values and required
        # condition before guarded effects.
    ):
        raise ControlApiProtocolError
    try:
        # Perform the protected run contract field operation before explicit failure
        # handling.
        return RunContractField(
            name=_string_field(document, "name"),
            kind=RunFieldKind(_string_field(document, "kind")),
            required=required,
            enum_values=tuple(enum_values),
            # Complete RunContractField only after its name and kind inputs are visible in run
            # contract field.
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


def _sniping_run_summary(value: object) -> PumpfunSnipingRunSummaryView:
    # Execute the sniping run summary workflow in explicit, reviewable steps.
    document = _require_object(value)
    expected = {
        "accepted_buy_count",
        "accepted_order_count",
        "account_deposit_locked_atomic",
        # Keep the account deposit paid atomic component named inside the expected
        # contract.
        "account_deposit_paid_atomic",
        "account_deposit_refunded_atomic",
        "adverse_slippage_count",
        "audit_hash",
        "buy_slippage_failure_count",
        # Keep the canonical result hash component named inside the expected contract.
        "canonical_result_hash",
        "cashback_receivable_atomic",
        "closed_position_count",
        "cooldown_skipped_count",
        "creator_fee_paid_atomic",
        # Keep the delivered event count component named inside the expected contract.
        "delivered_event_count",
        "economic_pnl_atomic",
        "execution_mode",
        "execution_attempt_id",
        "failed_buy_count",
        "failed_order_count",
        # Keep the failed sell count component named inside the expected contract.
        "failed_sell_count",
        "fill_count",
        "fill_hash",
        "filled_order_count",
        "filled_sell_count",
        "final_balances_count",
        # Keep the final balances digest component named inside the expected contract.
        "final_balances_digest",
        "historical_event_count",
        "historical_group_count",
        "gross_sell_settlement_atomic",
        "ledger_hash",
        "ledger_transaction_count",
        # Keep the logical run id component named inside the expected contract.
        "logical_run_id",
        "network_base_fee_paid_atomic",
        "network_id",
        "network_priority_fee_paid_atomic",
        "open_position_count",
        # Keep the position schema id component named inside the expected contract.
        "position_schema_id",
        "protocol_fee_paid_atomic",
        "real_liquidity_sufficient_filled_sell_count",
        "realized_cash_pnl_atomic",
        "rejected_order_count",
        "roundtrip_count",
        # Keep the roundtrip digest component named inside the expected contract.
        "roundtrip_digest",
        "run_artifact_id",
        "sell_slippage_failure_count",
        "settlement_policy_id",
        "summary_schema_id",
        "synthetic_funded_sell_atomic",
        "synthetic_liquidity_used_sell_count",
        "target_count",
        "unvalued_open_position_count",
        # Keep the valuation status component named inside the expected contract.
        "valuation_status",
        "valued_economic_pnl_subtotal_atomic",
        "venue_funded_sell_atomic",
        "favorable_slippage_count",
    }
    if set(document) != expected:
        # Fail the sniping run summary path with ControlApiProtocolError when expected and
        # document is true; do not continue ambiguously.
        raise ControlApiProtocolError
    try:
        # Perform the protected sniping run summary operation before explicit failure
        # handling.
        return PumpfunSnipingRunSummaryView(
            run_artifact_id=ArtifactId(_string_field(document, "run_artifact_id")),
            logical_run_id=LogicalRunId(_string_field(document, "logical_run_id")),
            execution_attempt_id=ExecutionAttemptId(
                _string_field(document, "execution_attempt_id")
                # Complete ExecutionAttemptId only after its execution attempt id and string
                # field inputs are visible in sniping run summary.
            ),
            network_id=NetworkId(_string_field(document, "network_id")),
            position_schema_id=PositionSchemaId(_string_field(document, "position_schema_id")),
            canonical_result_hash=ContentDigest(_string_field(document, "canonical_result_hash")),
            audit_hash=ContentDigest(_string_field(document, "audit_hash")),
            # Include ledger hash in the completed sniping run summary result.
            ledger_hash=ContentDigest(_string_field(document, "ledger_hash")),
            fill_hash=ContentDigest(_string_field(document, "fill_hash")),
            roundtrip_digest=ContentDigest(_string_field(document, "roundtrip_digest")),
            final_balances_digest=ContentDigest(_string_field(document, "final_balances_digest")),
            historical_group_count=_integer_field(document, "historical_group_count", minimum=0),
            # Include historical event count in the completed sniping run summary result.
            historical_event_count=_integer_field(document, "historical_event_count", minimum=0),
            delivered_event_count=_integer_field(document, "delivered_event_count", minimum=0),
            target_count=_integer_field(document, "target_count", minimum=0),
            cooldown_skipped_count=_integer_field(document, "cooldown_skipped_count", minimum=0),
            accepted_buy_count=_integer_field(document, "accepted_buy_count", minimum=0),
            # Include accepted order count in the completed sniping run summary result.
            accepted_order_count=_integer_field(document, "accepted_order_count", minimum=0),
            rejected_order_count=_integer_field(document, "rejected_order_count", minimum=0),
            filled_order_count=_integer_field(document, "filled_order_count", minimum=0),
            failed_order_count=_integer_field(document, "failed_order_count", minimum=0),
            failed_buy_count=_integer_field(document, "failed_buy_count", minimum=0),
            # Include failed sell count in the completed sniping run summary result.
            failed_sell_count=_integer_field(document, "failed_sell_count", minimum=0),
            closed_position_count=_integer_field(document, "closed_position_count", minimum=0),
            open_position_count=_integer_field(document, "open_position_count", minimum=0),
            ledger_transaction_count=_integer_field(
                document,
                # Pass ledger transaction count explicitly so _integer_field receives a
                # reviewable ledger transaction count and document input in sniping run
                # summary.
                "ledger_transaction_count",
                minimum=0,
                # Complete _integer_field only after its ledger transaction count and document
                # inputs are visible in sniping run summary.
            ),
            fill_count=_integer_field(document, "fill_count", minimum=0),
            roundtrip_count=_integer_field(document, "roundtrip_count", minimum=0),
            final_balances_count=_integer_field(document, "final_balances_count", minimum=0),
            realized_cash_pnl_atomic=_decimal_integer_field(
                # Pass signed explicitly so _decimal_integer_field receives a reviewable
                # realized cash pnl atomic and document input in sniping run summary.
                document,
                "realized_cash_pnl_atomic",
                signed=True,
            ),
            valuation_status=SnipingValuationStatus(_string_field(document, "valuation_status")),
            # Include unvalued open position count in the completed sniping run summary
            # result.
            unvalued_open_position_count=_integer_field(
                document,
                "unvalued_open_position_count",
                minimum=0,
                # Complete _integer_field only after its unvalued open position count and
                # document inputs are visible in sniping run summary.
            ),
            valued_economic_pnl_subtotal_atomic=_decimal_integer_field(
                document, "valued_economic_pnl_subtotal_atomic", signed=True
            ),
            economic_pnl_atomic=_optional_decimal_integer(
                # Pass signed explicitly so _optional_decimal_integer receives a
                # reviewable economic pnl atomic and document input in sniping run
                # summary.
                document["economic_pnl_atomic"],
                signed=True,
            ),
            cashback_receivable_atomic=_decimal_integer_field(
                document,
                # Pass cashback receivable atomic explicitly so _decimal_integer_field
                # receives a reviewable cashback receivable atomic and document input in
                # sniping run summary.
                "cashback_receivable_atomic",
                signed=False,
                # Complete _decimal_integer_field only after its cashback receivable atomic
                # and document inputs are visible in sniping run summary.
            ),
            # Include protocol fee paid atomic in the completed sniping run summary
            # result.
            protocol_fee_paid_atomic=_decimal_integer_field(
                document, "protocol_fee_paid_atomic", signed=False
            ),
            creator_fee_paid_atomic=_decimal_integer_field(
                document,
                # Pass creator fee paid atomic explicitly so _decimal_integer_field
                # receives a reviewable creator fee paid atomic and document input in
                # sniping run summary.
                "creator_fee_paid_atomic",
                signed=False,
                # Complete _decimal_integer_field only after its creator fee paid atomic and
                # document inputs are visible in sniping run summary.
            ),
            network_base_fee_paid_atomic=_decimal_integer_field(
                document, "network_base_fee_paid_atomic", signed=False
            ),
            network_priority_fee_paid_atomic=_decimal_integer_field(
                # Pass signed explicitly so _decimal_integer_field receives a reviewable
                # network priority fee paid atomic and document input in sniping run
                # summary.
                document,
                "network_priority_fee_paid_atomic",
                signed=False,
            ),
            account_deposit_paid_atomic=_decimal_integer_field(
                # Pass signed explicitly so _decimal_integer_field receives a reviewable
                # account deposit paid atomic and document input in sniping run summary.
                document,
                "account_deposit_paid_atomic",
                signed=False,
            ),
            # Include account deposit refunded atomic in the completed sniping run summary
            # result.
            account_deposit_refunded_atomic=_decimal_integer_field(
                document, "account_deposit_refunded_atomic", signed=False
            ),
            account_deposit_locked_atomic=_decimal_integer_field(
                document,
                # Pass account deposit locked atomic explicitly so _decimal_integer_field
                # receives a reviewable account deposit locked atomic and document input
                # in sniping run summary.
                "account_deposit_locked_atomic",
                signed=False,
                # Complete _decimal_integer_field only after its account deposit locked atomic
                # and document inputs are visible in sniping run summary.
            ),
            favorable_slippage_count=_integer_field(
                document, "favorable_slippage_count", minimum=0
            ),
            adverse_slippage_count=_integer_field(document, "adverse_slippage_count", minimum=0),
            # Include buy slippage failure count in the completed sniping run summary
            # result.
            buy_slippage_failure_count=_integer_field(
                document, "buy_slippage_failure_count", minimum=0
            ),
            sell_slippage_failure_count=_integer_field(
                document,
                # Pass sell slippage failure count explicitly so _integer_field receives a
                # reviewable sell slippage failure count and document input in sniping run
                # summary.
                "sell_slippage_failure_count",
                minimum=0,
                # Complete _integer_field only after its sell slippage failure count and
                # document inputs are visible in sniping run summary.
            ),
            summary_schema_id=_string_field(document, "summary_schema_id"),
            execution_mode=ExecutionMode(_string_field(document, "execution_mode")),
            settlement_policy_id=_string_field(document, "settlement_policy_id"),
            filled_sell_count=_optional_integer_field(document, "filled_sell_count", minimum=0),
            real_liquidity_sufficient_filled_sell_count=_optional_integer_field(
                document,
                "real_liquidity_sufficient_filled_sell_count",
                minimum=0,
            ),
            synthetic_liquidity_used_sell_count=_optional_integer_field(
                document,
                "synthetic_liquidity_used_sell_count",
                minimum=0,
            ),
            gross_sell_settlement_atomic=_optional_decimal_integer(
                document["gross_sell_settlement_atomic"], signed=False
            ),
            venue_funded_sell_atomic=_optional_decimal_integer(
                document["venue_funded_sell_atomic"], signed=False
            ),
            synthetic_funded_sell_atomic=_optional_decimal_integer(
                document["synthetic_funded_sell_atomic"], signed=False
            ),
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


def _roundtrip_page(
    # Keep the value input explicit in the roundtrip page contract.
    value: object,
    *,
    after: RoundTripCursor | None,
    limit: int,
) -> RoundTripPage:
    # Execute the roundtrip page workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {"items", "next_cursor"}:
        raise ControlApiProtocolError
    items = document["items"]
    if not isinstance(items, list) or len(items) > limit:
        # Fail the roundtrip page path with ControlApiProtocolError when limit, isinstance
        # and items is true; do not continue ambiguously.
        raise ControlApiProtocolError
    try:
        # Perform the protected roundtrip page operation before explicit failure handling.
        records = tuple(_roundtrip_record_from_api(item) for item in items)
        cursor = (
            None if document["next_cursor"] is None else _roundtrip_cursor(document["next_cursor"])
            # Complete the cursor group only after its semantic components are visible.
        )
        result = RoundTripPage(records, cursor)
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None
    if after is not None and result.items:
        # Handle the roundtrip page after is not None and result.items branch as a
        # distinct logical block.
        first = result.items[0]
        if (first.target_position.boundary_ordinal, first.roundtrip_id.hex) <= (
            after.target_boundary_ordinal,
            after.roundtrip_id.hex,
        ):
            # Fail the roundtrip page path with ControlApiProtocolError when boundary
            # ordinal, hex and target boundary ordinal is true; do not continue
            # ambiguously.
            raise ControlApiProtocolError
    return result


def _roundtrip_cursor(value: object) -> RoundTripCursor:
    # Execute the roundtrip cursor workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {"roundtrip_id", "target_boundary_ordinal"}:
        raise ControlApiProtocolError
    return RoundTripCursor(
        target_boundary_ordinal=_decimal_integer_field(
            # Pass signed explicitly so _decimal_integer_field receives a reviewable
            # target boundary ordinal and document input in roundtrip cursor.
            document,
            "target_boundary_ordinal",
            signed=False,
        ),
        roundtrip_id=ContentDigest(_string_field(document, "roundtrip_id")),
        # Complete RoundTripCursor only after its target boundary ordinal and roundtrip id
        # inputs are visible in roundtrip cursor.
    )


def _roundtrip_record_from_api(value: object) -> RoundTripRecord:
    document, schema_id = _roundtrip_api_document(value)
    return roundtrip_record_from_document(document, schema_id=schema_id)


def _roundtrip_api_document(value: object) -> tuple[dict[str, object], str]:
    # Execute the roundtrip api document workflow in explicit, reviewable steps.
    document = _require_object(value)
    expected = {
        "acquired_token_amount_atomic",
        "account_components",
        "account_profile_id",
        "asset_id",
        "buy",
        "cashback_receivable_atomic",
        "cooldown_consumed",
        # Keep the cooldown until ns component named inside the expected contract.
        "cooldown_until_ns",
        "creation_user_id",
        "developer_id",
        "economic_pnl_atomic",
        "execution_mode",
        "mtm_liquidity",
        "mtm_cash_pnl_atomic",
        # Keep the mtm liquidation value atomic component named inside the expected
        # contract.
        "mtm_liquidation_value_atomic",
        "mtm_status",
        "network_id",
        "position_schema_id",
        "quote_asset_id",
        # Keep the realized cash pnl atomic component named inside the expected contract.
        "realized_cash_pnl_atomic",
        "roundtrip_id",
        "result_schema_id",
        # Keep the sell component named inside the expected contract.
        "sell",
        "sell_landing_liquidity",
        "sell_reference_liquidity",
        "settled_synthetic_funded_atomic",
        "settled_venue_funded_atomic",
        "status",
        "target_event_id",
        "target_position",
        "target_time_ns",
        # Keep the venue id component named inside the expected contract.
        "venue_id",
    }
    if set(document) != expected or not isinstance(document["cooldown_consumed"], bool):
        raise ControlApiProtocolError
    network_id = _string_field(document, "network_id")
    # Assemble position schema id once so the roundtrip api document workflow shares one
    # value.
    position_schema_id = _string_field(document, "position_schema_id")
    schema_id = _string_field(document, "result_schema_id")
    if schema_id not in {ROUNDTRIP_RESULT_SCHEMA_V3, ROUNDTRIP_RESULT_SCHEMA_V4}:
        raise ControlApiProtocolError
    normalized: dict[str, object] = {
        "acquired_token_amount_atomic": _decimal_integer_field(
            document, "acquired_token_amount_atomic", signed=False
        ),
        "account_components": _account_components_api_document(document["account_components"]),
        "account_profile_id": _string_field(document, "account_profile_id"),
        "asset_id": _string_field(document, "asset_id"),
        "buy": _roundtrip_leg_api_document(
            # Pass expected side explicitly so _roundtrip_leg_api_document receives a
            # reviewable buy and document input in roundtrip api document.
            document["buy"],
            network_id,
            position_schema_id,
            expected_side="BUY",
        ),
        # Include cashback receivable atomic in the completed roundtrip api document
        # result.
        "cashback_receivable_atomic": _decimal_integer_field(
            document, "cashback_receivable_atomic", signed=False
        ),
        # Include cooldown consumed in the completed roundtrip api document result.
        "cooldown_consumed": document["cooldown_consumed"],
        "cooldown_until_ns": _optional_decimal_integer(document["cooldown_until_ns"], signed=False),
        "creation_user_id": _string_field(document, "creation_user_id"),
        "developer_id": _string_field(document, "developer_id"),
        "economic_pnl_atomic": _optional_decimal_integer(
            # Pass signed explicitly so _optional_decimal_integer receives a reviewable
            # economic pnl atomic and document input in roundtrip api document.
            document["economic_pnl_atomic"],
            signed=True,
        ),
        "mtm_cash_pnl_atomic": _optional_decimal_integer(
            document["mtm_cash_pnl_atomic"],
            # Pass signed explicitly so _optional_decimal_integer receives a reviewable
            # mtm cash pnl atomic and document input in roundtrip api document.
            signed=True,
            # Complete _optional_decimal_integer only after its mtm cash pnl atomic and
            # document inputs are visible in roundtrip api document.
        ),
        # Include mtm liquidation value atomic in the completed roundtrip api document
        # result.
        "mtm_liquidation_value_atomic": _optional_decimal_integer(
            document["mtm_liquidation_value_atomic"], signed=True
        ),
        "mtm_status": _string_field(document, "mtm_status"),
        "network_id": network_id,
        # Include position schema id in the completed roundtrip api document result.
        "position_schema_id": position_schema_id,
        "quote_asset_id": _string_field(document, "quote_asset_id"),
        "realized_cash_pnl_atomic": _optional_decimal_integer(
            document["realized_cash_pnl_atomic"], signed=True
        ),
        "roundtrip_id": _string_field(document, "roundtrip_id"),
        # Include sell in the completed roundtrip api document result.
        "sell": _roundtrip_leg_api_document(
            document["sell"], network_id, position_schema_id, expected_side="SELL"
        ),
        "status": _string_field(document, "status"),
        "target_event_id": _string_field(document, "target_event_id"),
        # Include target position in the completed roundtrip api document result.
        "target_position": _position_api_document(
            document["target_position"], network_id, position_schema_id
        ),
        "target_time_ns": _decimal_integer_field(document, "target_time_ns", signed=False),
        "venue_id": _string_field(document, "venue_id"),
        # Return the completed roundtrip api document result without a hidden fallback.
    }
    execution_mode = _string_field(document, "execution_mode")
    if schema_id == ROUNDTRIP_RESULT_SCHEMA_V3:
        if (
            execution_mode != ExecutionMode.EXOGENOUS_REPLAY.value
            or document["sell_reference_liquidity"] is not None
            or document["sell_landing_liquidity"] is not None
            or document["mtm_liquidity"] is not None
            or document["settled_venue_funded_atomic"] is not None
            or document["settled_synthetic_funded_atomic"] is not None
        ):
            raise ControlApiProtocolError
        return normalized, schema_id

    normalized.update(
        {
            "execution_mode": execution_mode,
            "mtm_liquidity": _liquidity_api_document(document["mtm_liquidity"]),
            "sell_landing_liquidity": _liquidity_api_document(document["sell_landing_liquidity"]),
            "sell_reference_liquidity": _liquidity_api_document(
                document["sell_reference_liquidity"]
            ),
            "settled_synthetic_funded_atomic": _decimal_integer_field(
                document, "settled_synthetic_funded_atomic", signed=False
            ),
            "settled_venue_funded_atomic": _decimal_integer_field(
                document, "settled_venue_funded_atomic", signed=False
            ),
        }
    )
    return normalized, schema_id


def _liquidity_api_document(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    document = _require_object(value)
    expected = {
        "asset_id",
        "observed_available_output_atomic",
        "policy_id",
        "required_output_atomic",
        "synthetic_shortfall_atomic",
    }
    if set(document) != expected:
        raise ControlApiProtocolError
    return {
        "asset_id": _string_field(document, "asset_id"),
        "observed_available_output_atomic": _decimal_integer_field(
            document, "observed_available_output_atomic", signed=False
        ),
        "policy_id": _string_field(document, "policy_id"),
        "required_output_atomic": _decimal_integer_field(
            document, "required_output_atomic", signed=False
        ),
        "synthetic_shortfall_atomic": _decimal_integer_field(
            document, "synthetic_shortfall_atomic", signed=False
        ),
    }


def _account_components_api_document(value: object) -> list[dict[str, object]]:
    """Translate either a suppressed target or the exact two resolved components."""

    if not isinstance(value, list) or len(value) not in {0, 2}:
        raise ControlApiProtocolError
    return [_account_component_api_document(item) for item in value]


def _account_component_api_document(value: object) -> dict[str, object]:
    """Translate decimal strings while retaining the strict domain field set."""

    document = _require_object(value)
    expected = {
        "asset_id",
        "attribution_id",
        "attribution_kind",
        "lifecycle",
        "locked_delta_atomic",
        "maximum_reserved_atomic",
        "paid_atomic",
        "refunded_atomic",
        "release_policy",
        "released_atomic",
        "requirement_schema_id",
        "scope",
    }
    if set(document) != expected:
        raise ControlApiProtocolError
    return {
        "asset_id": _string_field(document, "asset_id"),
        "attribution_id": _string_field(document, "attribution_id"),
        "attribution_kind": _string_field(document, "attribution_kind"),
        "lifecycle": _string_field(document, "lifecycle"),
        "locked_delta_atomic": _decimal_integer_field(document, "locked_delta_atomic", signed=True),
        "maximum_reserved_atomic": _decimal_integer_field(
            document, "maximum_reserved_atomic", signed=False
        ),
        "paid_atomic": _decimal_integer_field(document, "paid_atomic", signed=False),
        "refunded_atomic": _decimal_integer_field(document, "refunded_atomic", signed=False),
        "release_policy": _string_field(document, "release_policy"),
        "released_atomic": _decimal_integer_field(document, "released_atomic", signed=False),
        "requirement_schema_id": _string_field(document, "requirement_schema_id"),
        "scope": _string_field(document, "scope"),
    }


def _roundtrip_leg_api_document(
    value: object,
    network_id: str,
    position_schema_id: str,
    # Close the roundtrip leg api document signature after its explicit inputs.
    *,
    expected_side: str,
) -> dict[str, object] | None:
    # Execute the roundtrip leg api document workflow in explicit, reviewable steps.
    if value is None:
        return None
    document = _require_object(value)
    expected = {
        "amount_in_atomic",
        # Keep the creator fee atomic component named inside the expected contract.
        "creator_fee_atomic",
        "decision_position",
        "failure_code",
        "landing_out_atomic",
        "landing_position",
        # Keep the minimum out atomic component named inside the expected contract.
        "minimum_out_atomic",
        "network_base_fee_atomic",
        "network_priority_fee_atomic",
        "protocol_fee_atomic",
        "reference_out_atomic",
        # Keep the side component named inside the expected contract.
        "side",
        "signed_slippage_atomic",
    }
    if set(document) != expected or _string_field(document, "side") != expected_side:
        raise ControlApiProtocolError
    # Assemble landing once so the roundtrip leg api document workflow shares one value.
    landing = document["landing_position"]
    failure_code = document["failure_code"]
    if failure_code is not None and not isinstance(failure_code, str):
        raise ControlApiProtocolError
    return {
        # Include amount in atomic in the completed roundtrip leg api document result.
        "amount_in_atomic": _optional_decimal_integer(document["amount_in_atomic"], signed=False),
        "creator_fee_atomic": _decimal_integer_field(document, "creator_fee_atomic", signed=False),
        "decision_position": _position_api_document(
            document["decision_position"], network_id, position_schema_id
        ),
        # Include failure code in the completed roundtrip leg api document result.
        "failure_code": failure_code,
        "landing_out_atomic": _optional_decimal_integer(
            document["landing_out_atomic"], signed=False
        ),
        "landing_position": (
            # Return the completed roundtrip leg api document result without a hidden
            # fallback.
            None
            if landing is None
            else _position_api_document(landing, network_id, position_schema_id)
        ),
        "minimum_out_atomic": _decimal_integer_field(document, "minimum_out_atomic", signed=False),
        # Include network base fee atomic in the completed roundtrip leg api document
        # result.
        "network_base_fee_atomic": _decimal_integer_field(
            document, "network_base_fee_atomic", signed=False
        ),
        "network_priority_fee_atomic": _decimal_integer_field(
            document,
            # Pass network priority fee atomic explicitly so _decimal_integer_field
            # receives a reviewable network priority fee atomic and document input in
            # roundtrip leg api document.
            "network_priority_fee_atomic",
            signed=False,
            # Complete _decimal_integer_field only after its network priority fee atomic and
            # document inputs are visible in roundtrip leg api document.
        ),
        "protocol_fee_atomic": _decimal_integer_field(
            document, "protocol_fee_atomic", signed=False
        ),
        "reference_out_atomic": _decimal_integer_field(
            # Pass signed explicitly so _decimal_integer_field receives a reviewable
            # reference out atomic and document input in roundtrip leg api document.
            document,
            "reference_out_atomic",
            signed=False,
        ),
        "side": expected_side,
        # Include signed slippage atomic in the completed roundtrip leg api document
        # result.
        "signed_slippage_atomic": _optional_decimal_integer(
            document["signed_slippage_atomic"],
            signed=True,
            # Complete _optional_decimal_integer only after its signed slippage atomic and
            # document inputs are visible in roundtrip leg api document.
        ),
    }


def _position_api_document(
    value: object,
    network_id: str,
    # Keep the position schema id input explicit in the position api document contract.
    position_schema_id: str,
) -> dict[str, object]:
    # Execute the position api document workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "block_ordinal",
        "boundary_ordinal",
        "event_index",
        # Keep network id visible while evaluating the document, block ordinal and
        # boundary ordinal guard.
        "network_id",
        "position_schema_id",
        "transaction_index",
    }:
        raise ControlApiProtocolError
    # Evaluate the complete position api document network id, position schema id and
    # string field condition before guarded effects.
    if (
        _string_field(document, "network_id") != network_id
        or _string_field(document, "position_schema_id") != position_schema_id
    ):
        raise ControlApiProtocolError
    # Assemble event index once so the position api document workflow shares one value.
    event_index = document["event_index"]
    return {
        "block_ordinal": _integer_field(document, "block_ordinal", minimum=0),
        "boundary_ordinal": _decimal_integer_field(document, "boundary_ordinal", signed=False),
        "event_index": (
            # Include minimum in the completed position api document result.
            None if event_index is None else _integer_field(document, "event_index", minimum=0)
        ),
        "transaction_index": _integer_field(document, "transaction_index", minimum=-1),
    }


def _run_summary(value: object) -> RunSummaryView:
    # Execute the run summary workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "audit_hash",
        "canonical_result_hash",
        "canonicality",
        "completed_at",
        # Keep comparison visible while evaluating the document, audit hash and canonical
        # result hash guard.
        "comparison",
        "execution_attempt_id",
        "logical_run_id",
        "physical_settings",
        "run_artifact_id",
        "started_at",
        # Keep warnings visible while evaluating the document, audit hash and canonical
        # result hash guard.
        "warnings",
    }:
        raise ControlApiProtocolError
    warnings = document["warnings"]
    if (
        # Keep isinstance visible while evaluating the max run warnings, isinstance and
        # warnings guard.
        not isinstance(warnings, list)
        or len(warnings) > MAX_RUN_WARNINGS
        or not all(isinstance(item, str) for item in warnings)
    ):
        raise ControlApiProtocolError
    # Keep expected failures inside the run summary error boundary.
    try:
        # Perform the protected run summary operation before explicit failure handling.
        validated_warnings = validate_run_warnings(tuple(warnings))
        comparison = _run_comparison(document["comparison"])
        result = RunSummaryView(
            run_artifact_id=ArtifactId(_string_field(document, "run_artifact_id")),
            logical_run_id=LogicalRunId(_string_field(document, "logical_run_id")),
            # Keep the execution attempt id and string field ExecutionAttemptId step
            # visible while building result.
            execution_attempt_id=ExecutionAttemptId(
                _string_field(document, "execution_attempt_id")
            ),
            comparison=comparison,
            physical_settings=_run_physical_settings(document["physical_settings"]),
            # Keep the replay contract and string field ReplayContract step visible while
            # building result.
            canonicality=ReplayContract(_string_field(document, "canonicality")),
            started_at=_datetime_field(document, "started_at"),
            completed_at=_datetime_field(document, "completed_at"),
            warnings=validated_warnings,
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None
    # Evaluate the complete run summary hex, string field and document condition before
    # guarded effects.
    if (
        _string_field(document, "canonical_result_hash")
        != result.comparison.canonical_result_hash.hex
        or _string_field(document, "audit_hash") != result.comparison.audit_hash.hex
    ):
        # Fail the run summary path with ControlApiProtocolError when hex, string field
        # and document is true; do not continue ambiguously.
        raise ControlApiProtocolError
    return result


def _run_comparison(value: object) -> RunComparisonProjection:
    # Execute the run comparison workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "accepted_order_count",
        "audit_hash",
        "canonical_result_hash",
        # Keep delivered event count visible while evaluating the document, accepted order
        # count and audit hash guard.
        "delivered_event_count",
        "failed_order_count",
        "fill_count",
        "fill_hash",
        "filled_order_count",
        # Keep final balances count visible while evaluating the document, accepted order
        # count and audit hash guard.
        "final_balances_count",
        "final_balances_digest",
        "historical_event_count",
        "historical_group_count",
        "ledger_hash",
        # Keep ledger transaction count visible while evaluating the document, accepted
        # order count and audit hash guard.
        "ledger_transaction_count",
        "rejected_order_count",
    }:
        raise ControlApiProtocolError
    try:
        # Perform the protected run comparison operation before explicit failure handling.
        return RunComparisonProjection(
            canonical_result_hash=ContentDigest(_string_field(document, "canonical_result_hash")),
            audit_hash=ContentDigest(_string_field(document, "audit_hash")),
            ledger_hash=ContentDigest(_string_field(document, "ledger_hash")),
            fill_hash=ContentDigest(_string_field(document, "fill_hash")),
            # Include historical group count in the completed run comparison result.
            historical_group_count=_integer_field(
                document,
                "historical_group_count",
                minimum=0,
            ),
            # Include historical event count in the completed run comparison result.
            historical_event_count=_integer_field(
                document,
                "historical_event_count",
                minimum=0,
            ),
            # Include delivered event count in the completed run comparison result.
            delivered_event_count=_integer_field(
                document,
                "delivered_event_count",
                minimum=0,
            ),
            # Include accepted order count in the completed run comparison result.
            accepted_order_count=_integer_field(
                document,
                "accepted_order_count",
                minimum=0,
            ),
            # Include rejected order count in the completed run comparison result.
            rejected_order_count=_integer_field(
                document,
                "rejected_order_count",
                minimum=0,
            ),
            # Include filled order count in the completed run comparison result.
            filled_order_count=_integer_field(
                document,
                "filled_order_count",
                minimum=0,
            ),
            # Include failed order count in the completed run comparison result.
            failed_order_count=_integer_field(
                document,
                "failed_order_count",
                minimum=0,
            ),
            # Include ledger transaction count in the completed run comparison result.
            ledger_transaction_count=_integer_field(
                document,
                "ledger_transaction_count",
                minimum=0,
            ),
            # Include fill count in the completed run comparison result.
            fill_count=_integer_field(document, "fill_count", minimum=0),
            final_balances_count=_integer_field(
                document,
                "final_balances_count",
                minimum=0,
                # Complete _integer_field only after its final balances count and document
                # inputs are visible in run comparison.
            ),
            final_balances_digest=ContentDigest(_string_field(document, "final_balances_digest")),
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


# Define run physical settings as one focused operation with an explicit boundary.
def _run_physical_settings(value: object) -> RunPhysicalSettings:
    # Execute the run physical settings workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "backend",
        "output_buffer_rows",
        "reader_batch_rows",
        # Keep reader readahead visible while evaluating the document, backend and output
        # buffer rows guard.
        "reader_readahead",
        "schema",
        "threads",
    }:
        raise ControlApiProtocolError
    # Evaluate the complete run physical settings document and schema condition before
    # guarded effects.
    if document["schema"] != "backtest.run-physical-settings/v2":
        raise ControlApiProtocolError
    try:
        # Perform the protected run physical settings operation before explicit failure
        # handling.
        backend = RunBackend(_string_field(document, "backend"))
        return RunPhysicalSettings(
            backend=backend,
            reader_batch_rows=_integer_field(document, "reader_batch_rows", minimum=1),
            reader_readahead=_integer_field(document, "reader_readahead", minimum=1),
            # Include output buffer rows in the completed run physical settings result.
            output_buffer_rows=_integer_field(
                document,
                "output_buffer_rows",
                minimum=1,
            ),
            # Include threads in the completed run physical settings result.
            threads=_integer_field(document, "threads", minimum=1),
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


def _job_event(value: object) -> JobEventRecord:
    # Execute the job event workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "attempt_id",
        "created_at_ns",
        "event_id",
        # Keep event type visible while evaluating the document, attempt id and created at
        # ns guard.
        "event_type",
        "job_id",
        "progress",
        "state_version",
    }:
        # Fail the job event path with ControlApiProtocolError when document, attempt id
        # and created at ns is true; do not continue ambiguously.
        raise ControlApiProtocolError
    progress = document["progress"]
    try:
        # Perform the protected job event operation before explicit failure handling.
        return JobEventRecord(
            event_id=_integer_field(document, "event_id", minimum=1),
            job_id=JobId(_string_field(document, "job_id")),
            attempt_id=(
                None
                # Pass document explicitly so JobEventRecord receives a reviewable event
                # id and job id input in job event.
                if document["attempt_id"] is None
                else AttemptId(_string_field(document, "attempt_id"))
            ),
            event_type=_string_field(document, "event_type"),
            state_version=_integer_field(document, "state_version", minimum=0),
            # Include created at ns in the completed job event result.
            created_at_ns=_integer_field(document, "created_at_ns", minimum=0),
            progress=None if progress is None else _job_progress(progress),
        )
    except (TypeError, ValueError):
        raise ControlApiProtocolError from None


# Define job progress as one focused operation with an explicit boundary.
def _job_progress(value: object) -> JobProgressDetails:
    # Execute the job progress workflow in explicit, reviewable steps.
    document = _require_object(value)
    if set(document) != {
        "coalesced_events",
        "completed_units",
        "dropped_transport_frames",
        # Keep level visible while evaluating the document, coalesced events and completed
        # units guard.
        "level",
        "major_page_faults",
        "private_rss_bytes",
        "sequence",
        "stage",
        # Keep temporary disk bytes visible while evaluating the document, coalesced
        # events and completed units guard.
        "temporary_disk_bytes",
        "total_rss_bytes",
        "total_units",
    }:
        raise ControlApiProtocolError
    # Return the completed job progress result without a hidden fallback.
    return JobProgressDetails(
        sequence=_integer_field(document, "sequence", minimum=1),
        level=ProgressLevel(_string_field(document, "level")),
        stage=ProgressStage(_string_field(document, "stage")),
        completed_units=_optional_integer_field(document, "completed_units", minimum=0),
        # Include total units in the completed job progress result.
        total_units=_optional_integer_field(document, "total_units", minimum=0),
        coalesced_events=_integer_field(document, "coalesced_events", minimum=1),
        dropped_transport_frames=_integer_field(
            document,
            "dropped_transport_frames",
            # Pass minimum explicitly so _integer_field receives a reviewable dropped
            # transport frames and document input in job progress.
            minimum=0,
        ),
        private_rss_bytes=_optional_integer_field(document, "private_rss_bytes", minimum=0),
        total_rss_bytes=_optional_integer_field(document, "total_rss_bytes", minimum=0),
        major_page_faults=_optional_integer_field(document, "major_page_faults", minimum=0),
        # Include temporary disk bytes in the completed job progress result.
        temporary_disk_bytes=_optional_integer_field(
            document,
            "temporary_disk_bytes",
            minimum=0,
        ),
        # Complete JobProgressDetails only after its sequence and level inputs are visible in
        # job progress.
    )


def _string_field(document: dict[str, object], field: str) -> str:
    # Execute the string field workflow in explicit, reviewable steps.
    value = document.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _optional_page_cursor(value: object) -> str | None:
    """Validate an opaque continuation without interpreting its server-owned key."""

    if value is None:
        return None
    if not isinstance(value, str) or _PAGE_CURSOR.fullmatch(value) is None:
        raise ControlApiProtocolError
    return value


def _datetime_field(document: dict[str, object], field: str) -> datetime:
    value = _string_field(document, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    # The strict loopback protocol accepts only the canonical UTC spelling emitted by API.
    canonical = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if value != canonical:
        raise ValueError(f"{field} must be a canonical UTC timestamp")
    return parsed


def _integer_field(document: dict[str, object], field: str, *, minimum: int) -> int:
    # Execute the integer field workflow in explicit, reviewable steps.
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be a bounded integer")
    return value


def _optional_integer_field(
    # Keep the document input explicit in the optional integer field contract.
    document: dict[str, object],
    field: str,
    *,
    minimum: int,
) -> int | None:
    # Execute the optional integer field workflow in explicit, reviewable steps.
    value = document.get(field)
    if value is None:
        return None
    return _integer_field(document, field, minimum=minimum)


def _decimal_integer_field(
    # Keep the document input explicit in the decimal integer field contract.
    document: dict[str, object],
    field: str,
    *,
    signed: bool,
) -> int:
    # Return the completed decimal integer field result without a hidden fallback.
    return _decimal_integer(_string_field(document, field), signed=signed)


def _optional_decimal_integer(value: object, *, signed: bool) -> int | None:
    # Execute the optional decimal integer workflow in explicit, reviewable steps.
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional decimal integer must be a string or null")
    return _decimal_integer(value, signed=signed)


# Define decimal integer as one focused operation with an explicit boundary.
def _decimal_integer(value: str, *, signed: bool) -> int:
    # Execute the decimal integer workflow in explicit, reviewable steps.
    pattern = r"(?:0|[1-9][0-9]*)" if not signed else r"(?:0|-?[1-9][0-9]*)"
    if re.fullmatch(pattern, value) is None:
        raise ValueError("integer must use canonical decimal string encoding")
    return int(value)


def _safe_text(value: object, *, minimum: int = 1, maximum: int) -> bool:
    # Execute the safe text workflow in explicit, reviewable steps.
    return (
        isinstance(value, str)
        and minimum <= len(value) <= maximum
        and value == value.strip()
        and all(32 <= ord(character) < 127 for character in value)
        # Return the completed safe text result without a hidden fallback.
    )


__all__ = [
    "ControlApiError",
    "ControlApiProtocolError",
    "ControlApiUnavailableError",
    # Keep the local control api client component named inside the all contract.
    "LocalControlApiClient",
]
