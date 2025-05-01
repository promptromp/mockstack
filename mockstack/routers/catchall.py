"""Routes for the mockstack app."""

from fastapi import FastAPI, Request

from mockstack.config import Settings


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.route("/{full_path:path}", methods=["GET", "PATCH", "POST", "PUT", "DELETE"])
    async def catch_all(request: Request):
        """Catch all requests and delegate to the strategy."""
        return await app.state.strategy.apply(request)
