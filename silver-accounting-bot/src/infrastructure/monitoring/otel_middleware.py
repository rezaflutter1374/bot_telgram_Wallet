from __future__ import annotations

import time
import uuid

from aiohttp import web

from core.logging import correlation_id_scope
from core.telemetry import get_tracer


@web.middleware
async def otel_middleware(request: web.Request, handler: web.RequestHandler) -> web.StreamResponse:
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )
    request["correlation_id"] = correlation_id

    tracer = get_tracer()
    async with correlation_id_scope(correlation_id):
        start = time.monotonic()
        with tracer.start_as_current_span("http.request") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                duration = time.monotonic() - start
                span.set_attribute("http.status_code", exc.status)
                span.set_attribute("http.request_duration_seconds", duration)
                exc.headers["X-Correlation-ID"] = correlation_id
                raise
            except Exception:
                duration = time.monotonic() - start
                span.set_attribute("http.status_code", 500)
                span.set_attribute("http.request_duration_seconds", duration)
                raise
            else:
                duration = time.monotonic() - start
                span.set_attribute("http.status_code", response.status)
                span.set_attribute("http.request_duration_seconds", duration)
                response.headers["X-Correlation-ID"] = correlation_id
                return response
