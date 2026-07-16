from __future__ import annotations

import re
import sqlite3
from copy import deepcopy
from http import HTTPStatus
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException, Path as PathParameter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api_models import (
    HealthResponse,
    LivenessResponse,
    MetadataResponse,
    PDBeKBResponse,
    ProblemDetail,
    PublicIntegratedMDRecord,
    ReadinessResponse,
    SearchResponse,
    ValidationIssue,
)
from .observability import (
    HTTPMetrics,
    RequestObservabilityMiddleware,
    request_id,
    validate_allowed_hosts,
)
from .storage import SCHEMA_VERSION, SQLiteRecordStore


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FULL_GIT_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _public_record(record: dict) -> dict:
    payload = deepcopy(record)
    article = payload.get("article", {})
    if isinstance(article, dict) and str(article.get("source_uri", "")).casefold().startswith(
        "file:"
    ):
        article["source_uri"] = None
    for asset in payload.get("provenance", {}).get("assets", []):
        if isinstance(asset, dict):
            asset["local_path"] = None
            if str(asset.get("source_uri", "")).casefold().startswith("file:"):
                asset["source_uri"] = None
    for step in payload.get("provenance", {}).get("workflow_steps", []):
        if not isinstance(step, dict):
            continue
        for field in ("inputs", "outputs"):
            values = step.get(field, [])
            if not isinstance(values, list):
                continue
            step[field] = [
                "<redacted-local-path>"
                if isinstance(value, str)
                and (
                    value.casefold().startswith("file:")
                    or PurePath(value).is_absolute()
                    or PureWindowsPath(value).is_absolute()
                )
                else value
                for value in values
            ]
    return payload


def _http_error(status: int, *, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _problem_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    return {
        status: {
            "model": ProblemDetail,
            "description": HTTPStatus(status).phrase,
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                }
            },
        }
        for status in status_codes
    }


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", request_id()))


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str,
    title: str | None = None,
    errors: list[ValidationIssue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=f"urn:mdmeta:error:{code}",
        title=title or HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=_request_id(request),
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        content=problem.model_dump(mode="json", exclude_none=True),
        headers=headers,
        media_type="application/problem+json",
    )


def create_app(
    database_path: str | Path,
    *,
    read_only: bool = False,
    dataset_sha256: str = "unversioned",
    build_sha: str = "unknown",
    environment: str = "development",
    allowed_hosts: Sequence[str] = ("*",),
    docs_enabled: bool = True,
) -> FastAPI:
    environment = environment.casefold()
    hosts = validate_allowed_hosts(tuple(allowed_hosts))
    if environment not in {"development", "production"}:
        raise ValueError("environment must be development or production")
    if not hosts:
        raise ValueError("allowed_hosts must contain at least one host")
    if environment == "production":
        if not read_only:
            raise ValueError("production requires a read-only database")
        if not _SHA256.fullmatch(dataset_sha256.casefold()):
            raise ValueError("production requires a versioned dataset SHA-256")
        if not _FULL_GIT_SHA.fullmatch(build_sha.casefold()):
            raise ValueError("production requires a full 40- or 64-character build SHA")
        if "*" in hosts:
            raise ValueError("production does not allow an unrestricted Host header")
        if docs_enabled:
            raise ValueError("production interactive API documentation must be disabled")

    store = SQLiteRecordStore(database_path, read_only=read_only)
    app = FastAPI(
        title="MD Metadata Integration API",
        version=__version__,
        description="Evidence-linked literature, PDBe, UniProt, SIFTS and provenance records.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
    )
    app.state.record_store = store
    metrics = HTTPMetrics(
        version=__version__,
        build_sha=build_sha,
        dataset_sha256=dataset_sha256,
        article_count=store.count_articles(),
    )
    app.state.http_metrics = metrics

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = f"http-{exc.status_code}"
        detail = str(exc.detail)
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", code))
            detail = str(exc.detail.get("detail", HTTPStatus(exc.status_code).phrase))
        return _problem_response(
            request,
            status=exc.status_code,
            code=code,
            detail=detail,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        issues = [
            ValidationIssue(
                location=[
                    str(item) if not isinstance(item, int) else item
                    for item in error["loc"]
                ],
                message=str(error["msg"]),
                error_type=str(error["type"]),
            )
            for error in exc.errors()
        ]
        return _problem_response(
            request,
            status=422,
            code="request-validation-error",
            detail="request parameters failed validation",
            errors=issues,
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
        responses=_problem_responses(500),
    )
    def health() -> HealthResponse:
        return HealthResponse(status="ok", article_count=store.count_articles())

    @app.get("/livez", response_model=LivenessResponse)
    def liveness() -> LivenessResponse:
        return LivenessResponse(status="ok", version=__version__)

    @app.get(
        "/readyz",
        response_model=ReadinessResponse,
        responses=_problem_responses(503),
    )
    def readiness() -> ReadinessResponse:
        try:
            article_count = store.count_articles()
            schema_version = store.schema_version()
        except (sqlite3.Error, RuntimeError) as exc:
            raise _http_error(
                503,
                code="database-unavailable",
                detail="database unavailable",
            ) from exc
        if schema_version != SCHEMA_VERSION:
            raise _http_error(
                503,
                code="database-schema-incompatible",
                detail="database schema incompatible",
            )
        return ReadinessResponse(
            status="ready",
            version=__version__,
            database_schema_version=schema_version,
            article_count=article_count,
        )

    @app.get(
        "/metadata",
        response_model=MetadataResponse,
        responses=_problem_responses(500),
    )
    def metadata() -> MetadataResponse:
        return MetadataResponse(
            service="md-metadata-pipeline",
            version=__version__,
            record_schema="integrated-md-record-v1",
            database_schema_version=store.schema_version(),
            article_count=store.count_articles(),
            database_mode="read_only" if store.read_only else "read_write",
            dataset_sha256=dataset_sha256,
            build_sha=build_sha,
        )

    @app.get(
        "/records/{document_id}",
        response_model=PublicIntegratedMDRecord,
        responses=_problem_responses(404, 500),
    )
    def get_record(document_id: str) -> PublicIntegratedMDRecord:
        record = store.get(document_id.upper())
        if record is None:
            raise _http_error(404, code="record-not-found", detail="record not found")
        return PublicIntegratedMDRecord.model_validate(_public_record(record))

    @app.get(
        "/search",
        response_model=SearchResponse,
        responses=_problem_responses(400, 422, 500),
    )
    def search(
        pdb_id: str | None = Query(default=None, min_length=4, max_length=4),
        uniprot_accession: str | None = Query(default=None, min_length=6, max_length=10),
        limit: int = Query(default=25, ge=1, le=100),
    ) -> SearchResponse:
        if pdb_id is None and uniprot_accession is None:
            raise _http_error(
                400,
                code="missing-search-filter",
                detail="supply pdb_id or uniprot_accession",
            )
        records = store.search(
            pdb_id=pdb_id,
            uniprot_accession=uniprot_accession,
            limit=limit,
        )
        public_records = [
            PublicIntegratedMDRecord.model_validate(_public_record(row)) for row in records
        ]
        return SearchResponse(count=len(public_records), records=public_records)

    @app.get(
        "/pdbekb/{accession}",
        response_model=PDBeKBResponse,
        responses=_problem_responses(404, 422, 500),
    )
    def pdbekb_enrichment(
        accession: str = PathParameter(pattern=r"^[A-Za-z0-9]{6,10}$"),
    ) -> PDBeKBResponse:
        normalized = accession.upper()
        enrichments = store.get_pdbekb_enrichments(normalized)
        if not enrichments:
            raise _http_error(
                404,
                code="pdbekb-enrichment-not-found",
                detail="PDBe-KB enrichment not found",
            )
        return PDBeKBResponse(
            accession=normalized,
            count=len(enrichments),
            enrichments=enrichments,
        )

    @app.get("/metrics", include_in_schema=False, response_class=Response)
    def prometheus_metrics() -> Response:
        return Response(
            content=metrics.render(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    app.add_middleware(
        RequestObservabilityMiddleware,
        metrics=metrics,
        service_version=__version__,
        build_sha=build_sha,
        dataset_sha256=dataset_sha256,
        strict_security=environment == "production",
        allowed_hosts=hosts,
    )
    return app
