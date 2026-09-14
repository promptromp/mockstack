"""Routes for the homepage."""

from fastapi import APIRouter, FastAPI

from mockstack.config import Settings


def homepage_router_provider(app: FastAPI, settings: Settings) -> APIRouter:
    """Provide the homepage routes."""

    router = APIRouter()

    # `response_model=None` keeps the route as it was before the return annotation.
    @router.get("/", response_model=None)
    async def homepage() -> dict[str, str]:
        """Root endpoint."""
        return {"Hello": "World"}

    return router
