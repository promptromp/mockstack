"""Routes for the mockstack app."""

from fastapi import FastAPI, Request, Response

from mockstack.config import Settings
from mockstack.strategies.base import BaseStrategy


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "DELETE"],
    )
    async def catch_all(request: Request) -> Response:
        """Catch all requests and delegate to the strategy.

        HEAD and OPTIONS are routed too (FastAPI does not add them implicitly); a
        strategy that does not support them answers 405 itself.
        """
        strategy: BaseStrategy = app.state.strategy
        return await strategy.apply(request)
