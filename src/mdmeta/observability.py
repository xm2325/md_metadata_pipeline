from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


_REQUEST_ID = ContextVar[str]("mdmeta_request_id", default="unknown")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_METRIC_METHODS = {"GET", "HEAD", "OPTIONS"}
_HOST_DELIMITERS = ("@", "/", "\\", "?", "#", "\r", "\n", "\t", " ")
_LOG_FIELDS = (
    "event",
    "request_id",
    "method",
    "route",
    "status",
    "duration_ms",
    "service",
    "version",
    "build_sha",
    "dataset_sha256",
    "exception_raised",
)


def request_id() -> str:
    return _REQUEST_ID.get()


def validate_allowed_hosts(allowed_hosts: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize trusted Host patterns and reject ambiguous wildcard/userinfo forms."""

    normalized = tuple(host.strip().casefold() for host in allowed_hosts)
    if not normalized or any(not host for host in normalized):
        raise ValueError("allowed_hosts must contain at least one non-empty host")
    if len(set(normalized)) != len(normalized):
        raise ValueError("allowed_hosts must not contain duplicate patterns")
    if "*" in normalized and len(normalized) != 1:
        raise ValueError("the unrestricted Host wildcard must be the only pattern")
    for pattern in normalized:
        if any(character in pattern for character in _HOST_DELIMITERS):
            raise ValueError("allowed host patterns must contain hostnames only")
        if "*" in pattern and (
            pattern == "*." or pattern.count("*") != 1 or not pattern.startswith("*.")
        ):
            if pattern != "*":
                raise ValueError("host wildcards are supported only as '*.' domain prefixes")
        if ":" in pattern:
            try:
                ip_address(pattern)
            except ValueError as exc:
                raise ValueError(
                    "allowed host patterns must not include a scheme or port"
                ) from exc
    return normalized


class JSONLogFormatter(logging.Formatter):
    """Small dependency-free JSON formatter for application and access events."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.casefold(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class _DynamicStdoutHandler(logging.StreamHandler):
    """Resolve stdout at emit time so test capture and process redirection remain valid."""

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


def configure_json_logging(level: str) -> None:
    """Configure only project loggers; Uvicorn lifecycle logs remain independent."""

    handler = _DynamicStdoutHandler()
    handler.setFormatter(JSONLogFormatter())
    logger = logging.getLogger("mdmeta")
    logger.handlers = [handler]
    numeric_level = 5 if level.casefold() == "trace" else getattr(logging, level.upper())
    if numeric_level == 5:
        logging.addLevelName(5, "TRACE")
    logger.setLevel(numeric_level)
    logger.propagate = False


class HTTPMetrics:
    """Per-process metrics with bounded labels suitable for one worker per container."""

    def __init__(
        self,
        *,
        version: str,
        build_sha: str,
        dataset_sha256: str,
        article_count: int,
    ) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "mdmeta_http_requests_total",
            "Completed HTTP requests.",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self.duration = Histogram(
            "mdmeta_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self.in_flight = Gauge(
            "mdmeta_http_requests_in_flight",
            "HTTP requests currently being handled.",
            registry=self.registry,
        )
        self.build_info = Gauge(
            "mdmeta_build_info",
            "Build and dataset identity for the running service.",
            ("version", "build_sha", "dataset_sha256"),
            registry=self.registry,
        )
        self.dataset_articles = Gauge(
            "mdmeta_dataset_articles",
            "Articles in the immutable dataset snapshot at application startup.",
            registry=self.registry,
        )
        self.build_info.labels(
            version=version,
            build_sha=build_sha,
            dataset_sha256=dataset_sha256,
        ).set(1)
        self.dataset_articles.set(article_count)

    def observe(self, *, method: str, route: str, status: int, duration: float) -> None:
        self.requests.labels(method=method, route=route, status=str(status)).inc()
        self.duration.labels(method=method, route=route).observe(duration)

    def render(self) -> bytes:
        return generate_latest(self.registry)


class RequestObservabilityMiddleware:
    """Correlate, secure, measure and log every HTTP response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        metrics: HTTPMetrics,
        service_version: str,
        build_sha: str,
        dataset_sha256: str,
        strict_security: bool,
        allowed_hosts: tuple[str, ...],
    ) -> None:
        self.app = app
        self.metrics = metrics
        self.service_version = service_version
        self.build_sha = build_sha
        self.dataset_sha256 = dataset_sha256
        self.strict_security = strict_security
        self.allowed_hosts = validate_allowed_hosts(allowed_hosts)
        self.logger = logging.getLogger("mdmeta.access")

    @staticmethod
    def _request_id(scope: Scope) -> str:
        supplied = Headers(scope=scope).get("x-request-id", "")
        if _REQUEST_ID_PATTERN.fullmatch(supplied):
            return supplied
        return uuid.uuid4().hex

    def _host_allowed(self, scope: Scope) -> bool:
        host_header = Headers(scope=scope).get("host", "")
        if any(character in host_header for character in _HOST_DELIMITERS):
            return False
        try:
            parsed_host = urlsplit(f"//{host_header}")
            host = (parsed_host.hostname or "").casefold()
            _ = parsed_host.port
        except ValueError:
            return False
        if host_header.endswith(":"):
            return False
        if "*" in self.allowed_hosts:
            return bool(host)
        return any(
            host == pattern
            or (pattern.startswith("*.") and host.endswith(pattern[1:]))
            for pattern in self.allowed_hosts
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = self._request_id(scope)
        state = scope.setdefault("state", {})
        state["request_id"] = correlation_id
        token = _REQUEST_ID.set(correlation_id)
        method = str(scope.get("method", "UNKNOWN")).upper()
        metric_method = method if method in _METRIC_METHODS else "OTHER"
        started = time.perf_counter()
        status = 500
        exception_raised = False
        response_started = False
        self.metrics.in_flight.inc()

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = correlation_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = (
                    "accelerometer=(), camera=(), geolocation=(), microphone=()"
                )
                csp = (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                    if self.strict_security
                    else "frame-ancestors 'none'; base-uri 'none'"
                )
                headers["Content-Security-Policy"] = csp
            await send(message)

        try:
            if self._host_allowed(scope):
                await self.app(scope, receive, send_with_headers)
            else:
                response = JSONResponse(
                    status_code=400,
                    content={
                        "type": "urn:mdmeta:error:invalid-host",
                        "title": "Bad Request",
                        "status": 400,
                        "detail": "request Host is not allowed",
                        "instance": str(scope.get("path", "/")),
                        "code": "invalid-host",
                        "request_id": correlation_id,
                    },
                    media_type="application/problem+json",
                )
                await response(scope, receive, send_with_headers)
        except Exception as exc:
            exception_raised = True
            if response_started:
                raise
            route_object = scope.get("route")
            route = str(getattr(route_object, "path", "unmatched"))
            logging.getLogger("mdmeta.error").error(
                "unhandled_request_exception",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    "event": "unhandled_request_exception",
                    "request_id": correlation_id,
                    "method": method,
                    "route": route,
                    "status": 500,
                    "service": "md-metadata-pipeline",
                    "version": self.service_version,
                    "build_sha": self.build_sha,
                    "dataset_sha256": self.dataset_sha256,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "type": "urn:mdmeta:error:internal-server-error",
                    "title": "Internal Server Error",
                    "status": 500,
                    "detail": "an unexpected server error occurred",
                    "instance": str(scope.get("path", "/")),
                    "code": "internal-server-error",
                    "request_id": correlation_id,
                },
                media_type="application/problem+json",
            )
            await response(scope, receive, send_with_headers)
        finally:
            duration = time.perf_counter() - started
            route_object = scope.get("route")
            route = str(getattr(route_object, "path", "unmatched"))
            self.metrics.in_flight.dec()
            self.metrics.observe(
                method=metric_method,
                route=route,
                status=status,
                duration=duration,
            )
            self.logger.info(
                "http_request_complete",
                extra={
                    "event": "http_request_complete",
                    "request_id": correlation_id,
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(duration * 1000, 3),
                    "service": "md-metadata-pipeline",
                    "version": self.service_version,
                    "build_sha": self.build_sha,
                    "dataset_sha256": self.dataset_sha256,
                    "exception_raised": exception_raised,
                },
            )
            _REQUEST_ID.reset(token)
