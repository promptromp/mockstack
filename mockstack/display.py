"""Display and logging functionality."""

import logging
from importlib import metadata

from fastapi import FastAPI

from mockstack.config import Settings


def announce(app: FastAPI, settings: Settings):
    """Log the startup message with the active settings."""
    logger = logging.getLogger("uvicorn")
    extra = {"markup": True}

    version = metadata.version("mockstack")

    logger.info(
        f"[bold medium_purple]mockstack[/bold medium_purple] ready to roll. version: [medium_purple]{version}[/medium_purple]. "
        f"debug: [medium_purple]{settings.debug}[/medium_purple]. "
        f"strategy: [medium_purple]{settings.strategy}[/medium_purple]. ",
        extra=extra,
    )
    logger.info(str(app.state.strategy), extra=extra)
    logger.info(
        f"[medium_purple]OpenTelemetry[/medium_purple] enabled: [medium_purple]{settings.opentelemetry.enabled}[/medium_purple],\n "
        f"endpoint: [medium_purple]{settings.opentelemetry.endpoint}[/medium_purple],\n "
        f"capture_response_body: [medium_purple]{settings.opentelemetry.capture_response_body}[/medium_purple]",
        extra=extra,
    )
