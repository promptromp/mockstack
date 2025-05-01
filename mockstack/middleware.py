"""Middleware definitionsfor the mockstack app."""

import time

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.propagate import extract

from mockstack.config import Settings
from mockstack.telemetry import extract_body, span_name_for


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
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))

            response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)

            # Nb. persisting response body can hamper performance,
            # expose sensitive / PII data, and / or may not be needed.
            # it is therefore an opt-in setting.
            if settings.opentelemetry.capture_response_body:
                body = await extract_body(response)

                # for semantics of payload collection see:
                # https://github.com/open-telemetry/oteps/pull/234
                span.set_attribute("http.response.body", body)

                # recreate response with the same body since when consuming it to log it above
                # we effectively "deplete" the iterator.
                response = Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

            return response
