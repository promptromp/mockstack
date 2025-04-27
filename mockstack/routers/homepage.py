"""Routes for the homepage."""

from fastapi import APIRouter, FastAPI

from mockstack.config import Settings


def homepage_router_provider(app: FastAPI, settings: Settings) -> APIRouter:
    """Provide the homepage routes."""

    router = APIRouter()

    @router.get("/")
    async def homepage():
        """Root endpoint."""
        return {"Hello": "World"}

    return router
