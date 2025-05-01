"""Middleware definitionsfor the mockstack app."""

import time

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.propagate import extract

from mockstack.config import Settings
from mockstack.constants import SENSITIVE_HEADERS
from mockstack.telemetry import (
    span_name_for,
    with_request_attributes,
    with_response_attributes,
    with_response_body,
)


def middleware_provider(app: FastAPI, settings: Settings) -> None:
    """Instrument the middlewares to the mockstack app."""

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    @app.middleware("http")
    async def instrument_opentelemetry(request: Request, call_next):
        tracer = trace.get_tracer(__name__)
        ctx = extract(request.headers)
        with tracer.start_as_current_span(span_name_for(request), context=ctx) as span:
            span = with_request_attributes(
                request, span, sensitive_headers=SENSITIVE_HEADERS
            )

            # Make the current opentelemetry span available to the request.
            # This is useful for strategies that need to add custom attributes
            # to the span associated with the request.
            request.state.span = span

            response = await call_next(request)

            span = with_response_attributes(
                response, span, sensitive_headers=SENSITIVE_HEADERS
            )

            if settings.opentelemetry.capture_response_body:
                response, span = await with_response_body(response, span)

            return response
