"""Application entrypoints."""

from fastapi import FastAPI
from typer import Typer

from mockstack.config import settings_provider
from mockstack.lifespan import lifespan_provider
from mockstack.middleware import middleware_provider
from mockstack.routers.catchall import catchall_router_provider
from mockstack.routers.homepage import homepage_router_provider
from mockstack.strategies.factory import strategy_provider
from mockstack.telemetry import opentelemetry_provider

cli = Typer()


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


@cli.command()
def run(host: str = "0.0.0.0", port: int = 8000):
    """mockstack run CLI entrypoint."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=host, port=port)


@cli.command()
def version():
    """mockstack version CLI entrypoint."""
    from importlib.metadata import version

    pkg_version = version("mockstack")
    print(f"mockstack {pkg_version}")


if __name__ == "__main__":
    cli()
