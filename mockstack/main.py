"""Application entrypoints."""

from collections.abc import Sequence

import uvicorn
from fastapi import FastAPI

from mockstack.cli import SETTINGS_ERRORS, build_parser, parse_settings, report_for, settings_source
from mockstack.config import Settings, settings_provider
from mockstack.lifespan import lifespan_provider
from mockstack.middleware import middleware_provider
from mockstack.routers.catchall import catchall_router_provider
from mockstack.strategies.factory import strategy_provider
from mockstack.strategies.proxyrules import RulesFileError
from mockstack.telemetry import opentelemetry_provider


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the fastapi app and bootstrap all dependencies."""
    settings = settings or settings_provider()

    # FastAPI adds its documentation routes ahead of the catch-all route; without an
    # OpenAPI URL it adds none of them.
    app = FastAPI(
        lifespan=lifespan_provider(settings),
        openapi_url="/openapi.json" if settings.openapi_docs_enabled else None,
    )

    strategy_provider(app, settings)
    middleware_provider(app, settings)
    opentelemetry_provider(app, settings)

    catchall_router_provider(app, settings)

    return app


def run(argv: Sequence[str] | None = None) -> None:
    """Run the mockstack server with settings from ``argv`` (by default the command line).

    Invalid settings and a rules file that does not load are printed without a traceback
    and exit with status 2. Each ``try`` covers only the step that raises the errors it
    catches, so a bug elsewhere keeps its traceback.
    """
    parser = build_parser()
    source = settings_source(parser)
    try:
        settings = parse_settings(source, argv)
    except SETTINGS_ERRORS as exc:
        parser.exit_with(report_for(exc))

    try:
        app = create_app(settings=settings)
    except RulesFileError as exc:
        parser.exit_with(report_for(exc))

    uvicorn.run(app, host=settings.host, port=settings.port)
