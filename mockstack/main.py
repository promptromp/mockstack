"""Application entrypoints."""

from fastapi import FastAPI

from mockstack.config import settings_provider
from mockstack.lifespan import lifespan_provider
from mockstack.middleware import middleware_provider
from mockstack.opentelemetry import opentelemetry_provider
from mockstack.routers.catchall import catchall_router_provider
from mockstack.routers.homepage import homepage_router_provider
from mockstack.strategies.factory import strategy_provider


def create_app() -> FastAPI:
    """Create the FastAPI app."""
    settings = settings_provider()

    app = FastAPI(lifespan=lifespan_provider(settings))

    strategy_provider(app, settings)
    middleware_provider(app, settings)
    opentelemetry_provider(app, settings)

    homepage_router_provider(app, settings)
    catchall_router_provider(app, settings)

    return app


# expose top-level app object for fastapi cli
app = create_app()
