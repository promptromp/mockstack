"""Middleware definitions for the mockstack app."""

import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from mockstack.config import Settings


def middleware_provider(app: FastAPI, settings: Settings) -> None:
    """Add the middlewares every mockstack app has.

    The tracing middleware is added by ``mockstack.telemetry.opentelemetry_provider``,
    only when OpenTelemetry is enabled.
    """

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response
