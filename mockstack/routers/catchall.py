"""Routes for the mockstack app."""

import time

from fastapi import FastAPI, Request

from mockstack.config import Settings


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    @app.route("/{full_path:path}", methods=["GET", "PATCH", "POST", "PUT", "DELETE"])
    async def catch_all(request: Request):
        """Catch all requests and delegate to the strategy."""
        strategy = app.state.strategy
        results = await strategy.apply(request)
        return results
