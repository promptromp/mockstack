"""Routes for the mockstack app."""

from fastapi import FastAPI, Request
from opentelemetry import trace

from mockstack.config import Settings


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.route("/{full_path:path}", methods=["GET", "PATCH", "POST", "PUT", "DELETE"])
    async def catch_all(request: Request):
        """Catch all requests and delegate to the strategy."""
        tracer = trace.get_tracer(__name__)
        with tracer.start_span(name="mockstack-http-request") as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url.path))
            return await app.state.strategy.apply(request)
