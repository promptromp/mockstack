"""Routes for the mockstack app."""

from fastapi import FastAPI, Request
from opentelemetry import trace
from opentelemetry.propagate import extract

from mockstack.config import Settings
from mockstack.telemetry import span_name_for


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.route("/{full_path:path}", methods=["GET", "PATCH", "POST", "PUT", "DELETE"])
    async def catch_all(request: Request):
        """Catch all requests and delegate to the strategy."""
        tracer = trace.get_tracer(__name__)
        ctx = extract(request.headers)
        with tracer.start_as_current_span(span_name_for(request), context=ctx) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))

            response = await app.state.strategy.apply(request)

            span.set_attribute("http.status_code", response.status_code)

            # Nb. persisting response body can hamper performance,
            # expose sensitive / PII data, and / or may not be needed.
            # it is therefore an opt-in setting.
            if settings.opentelemetry.capture_response_body:
                span.set_attribute("response", response.body)

            return response
