"""Routes for the mockstack app."""

from fastapi import APIRouter, FastAPI, Request

from mockstack.config import Settings


def catchall_router_provider(app: FastAPI, settings: Settings) -> APIRouter:
    """Create the catch-all routes for the mockstack app."""

    router = APIRouter()

    @router.api_route(
        "/{full_path:path}", methods=["GET", "PATCH", "POST", "PUT", "DELETE"]
    )
    async def catch_all(full_path: str, request: Request):
        """Catch all requests and delegate to the strategy."""

        with settings.strategy.handle(full_path, request.method) as strategy:
            return await strategy.handle(full_path, request)

    return router
