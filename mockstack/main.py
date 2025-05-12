"""Application entrypoints."""

from fastapi import FastAPI
from pydantic_settings import CliApp, CliSettingsSource

from mockstack.config import CliSettings, Settings, settings_provider
from mockstack.lifespan import lifespan_provider
from mockstack.middleware import middleware_provider
from mockstack.routers.catchall import catchall_router_provider
from mockstack.routers.homepage import homepage_router_provider
from mockstack.strategies.factory import strategy_provider
from mockstack.telemetry import opentelemetry_provider


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the fastapi app and bootstrap all dependencies."""
    settings = settings or settings_provider()

    app = FastAPI(lifespan=lifespan_provider(settings))

    strategy_provider(app, settings)
    middleware_provider(app, settings)
    opentelemetry_provider(app, settings)

    homepage_router_provider(app, settings)
    catchall_router_provider(app, settings)

    return app


def run():
    """run the mockstack server."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    cli_settings = CliSettingsSource(CliSettings, root_parser=parser)
    settings = CliApp.run(CliSettings, cli_settings_source=cli_settings)

    app = create_app(settings=settings)

    uvicorn.run(app, host=settings.host, port=settings.port)


def version():
    """display mockstack version."""
    from importlib.metadata import version

    pkg_version = version("mockstack")
    print(f"mockstack v{pkg_version}")
