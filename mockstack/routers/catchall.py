"""Routes for the mockstack app."""

from fastapi import FastAPI, Request

from mockstack.config import Settings


def catchall_router_provider(app: FastAPI, settings: Settings) -> None:
    """Create the catch-all routes for the mockstack app."""

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "DELETE"],
    )
    async def catch_all(request: Request):
        """Catch all requests and delegate to the strategy.

        HEAD and OPTIONS are routed too (FastAPI does not add them implicitly); a
        strategy that does not support them answers 405 itself.
        """
        return await app.state.strategy.apply(request)
